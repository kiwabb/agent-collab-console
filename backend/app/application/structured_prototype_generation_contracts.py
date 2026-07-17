from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.application.structured_prototype_contracts import StructuredPrototypeContractError

GENERATION_CONTRACT_VERSION = 3
GENERATION_BLUEPRINT_CONTRACT_VERSION = 3
GENERATION_FOUNDATION_CONTRACT_VERSION = 3
GENERATION_PAGE_CONTRACT_VERSION = 3
GENERATION_MAX_ARTIFACT_BYTES = 512 * 1024

GenerationTaskKind = Literal[
    "generation_blueprint",
    "generation_foundation",
    "generation_page",
]
GenerationComponentType = Literal[
    "Stack",
    "Grid",
    "Form",
    "Text",
    "Input",
    "Button",
    "Table",
]
REQUIRED_GENERATION_COMPONENT_TYPES = frozenset(
    {"Stack", "Grid", "Form", "Text", "Input", "Button", "Table"}
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
    behavior_intent_key: TechnicalKey
    target_page_key: TechnicalKey


class GenerationNullValueV2(StrictGenerationModel):
    type: Literal["null"]


class GenerationBooleanValueV2(StrictGenerationModel):
    type: Literal["boolean"]
    value: bool


class GenerationIntegerValueV2(StrictGenerationModel):
    type: Literal["integer"]
    value: int


class GenerationStringValueV2(StrictGenerationModel):
    type: Literal["string"]
    value: Annotated[str, Field(max_length=8_000)]


class GenerationEnumValueV2(StrictGenerationModel):
    type: Literal["enum"]
    value: TechnicalKey


GenerationRuntimeValueV2 = Annotated[
    GenerationNullValueV2
    | GenerationBooleanValueV2
    | GenerationIntegerValueV2
    | GenerationStringValueV2
    | GenerationEnumValueV2,
    Field(discriminator="type"),
]


class GenerationRoleIntentV2(StrictGenerationModel):
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=80)]


class GenerationEntityFieldIntentV2(StrictGenerationModel):
    key: TechnicalKey
    value_type: Literal["boolean", "integer", "string", "enum"]
    nullable: bool


class GenerationEntityIntentV2(StrictGenerationModel):
    key: TechnicalKey
    fields: Annotated[list[GenerationEntityFieldIntentV2], Field(max_length=100)]

    @model_validator(mode="after")
    def validate_fields(self) -> GenerationEntityIntentV2:
        _require_unique((field.key for field in self.fields), "entity field key")
        return self


class GenerationVariableIntentV2(StrictGenerationModel):
    key: TechnicalKey
    value_type: Literal["null", "boolean", "integer", "string", "enum", "entityRef"]
    nullable: bool
    entity_schema_key: TechnicalKey | None
    default_value: GenerationRuntimeValueV2

    @model_validator(mode="after")
    def validate_default(self) -> GenerationVariableIntentV2:
        if self.value_type == "entityRef":
            if (
                self.entity_schema_key is None
                or self.default_value.type != "null"
                or not self.nullable
            ):
                raise ValueError(
                    "entityRef variable requires a schema, nullable=true, and a null default"
                )
            return self
        if self.entity_schema_key is not None:
            raise ValueError("only entityRef variables may declare an entity schema")
        if self.default_value.type == "null":
            if not self.nullable:
                raise ValueError("non-nullable variable cannot use a null default")
        elif self.default_value.type != self.value_type:
            raise ValueError("variable default type must match its value type")
        return self


class GenerationFormFieldIntentV2(StrictGenerationModel):
    key: TechnicalKey
    value_type: Literal["string", "integer"]
    initial_value: GenerationStringValueV2 | GenerationIntegerValueV2
    required: bool
    min_integer: int | None

    @model_validator(mode="after")
    def validate_initial_value(self) -> GenerationFormFieldIntentV2:
        if self.initial_value.type != self.value_type:
            raise ValueError("form field initial value type must match its value type")
        if self.value_type == "string" and self.min_integer is not None:
            raise ValueError("string form field cannot declare minInteger")
        return self


class GenerationFormIntentV2(StrictGenerationModel):
    key: TechnicalKey
    page_key: TechnicalKey
    fields: Annotated[list[GenerationFormFieldIntentV2], Field(max_length=100)]

    @model_validator(mode="after")
    def validate_fields(self) -> GenerationFormIntentV2:
        _require_unique((field.key for field in self.fields), "form field key")
        return self


class GenerationLiteralExpressionV2(StrictGenerationModel):
    kind: Literal["literal"]
    value: GenerationRuntimeValueV2


class GenerationVariableExpressionV2(StrictGenerationModel):
    kind: Literal["variable"]
    variable_key: TechnicalKey


class GenerationFormFieldExpressionV2(StrictGenerationModel):
    kind: Literal["formField"]
    form_key: TechnicalKey
    field_key: TechnicalKey


class GenerationEventEntityRefExpressionV2(StrictGenerationModel):
    kind: Literal["eventEntityRef"]


GenerationEntityRefExpressionV2 = (
    GenerationVariableExpressionV2 | GenerationEventEntityRefExpressionV2
)


class GenerationEntityFieldExpressionV2(StrictGenerationModel):
    kind: Literal["entityField"]
    entity_ref: GenerationEntityRefExpressionV2
    schema_key: TechnicalKey
    field_key: TechnicalKey
    fallback: GenerationRuntimeValueV2


GenerationExpressionV2 = Annotated[
    GenerationLiteralExpressionV2
    | GenerationVariableExpressionV2
    | GenerationFormFieldExpressionV2
    | GenerationEventEntityRefExpressionV2
    | GenerationEntityFieldExpressionV2,
    Field(discriminator="kind"),
]


class GenerationAllPredicateV2(StrictGenerationModel):
    kind: Literal["all"]
    items: Annotated[list[GenerationPredicateV2], Field(min_length=1, max_length=20)]


class GenerationRoleIsPredicateV2(StrictGenerationModel):
    kind: Literal["roleIs"]
    role_key: TechnicalKey


class GenerationFormValidPredicateV2(StrictGenerationModel):
    kind: Literal["formValid"]
    form_key: TechnicalKey


class GenerationComparePredicateV2(StrictGenerationModel):
    kind: Literal["compare"]
    operator: Literal["eq", "ne"]
    left: GenerationExpressionV2
    right: GenerationExpressionV2


GenerationPredicateV2 = Annotated[
    GenerationAllPredicateV2
    | GenerationRoleIsPredicateV2
    | GenerationFormValidPredicateV2
    | GenerationComparePredicateV2,
    Field(discriminator="kind"),
]


class GenerationSetVariableEffectV2(StrictGenerationModel):
    kind: Literal["setVariable"]
    variable_key: TechnicalKey
    value: GenerationExpressionV2


class GenerationValidateFormEffectV2(StrictGenerationModel):
    kind: Literal["validateForm"]
    form_key: TechnicalKey


class GenerationFieldAssignmentV2(StrictGenerationModel):
    field_key: TechnicalKey
    value: GenerationExpressionV2


class GenerationCreateEntityEffectV2(StrictGenerationModel):
    kind: Literal["createEntity"]
    schema_key: TechnicalKey
    result_variable_key: TechnicalKey
    values: Annotated[list[GenerationFieldAssignmentV2], Field(max_length=100)]


class GenerationUpdateEntityEffectV2(StrictGenerationModel):
    kind: Literal["updateEntity"]
    schema_key: TechnicalKey
    entity_ref: GenerationEntityRefExpressionV2
    updates: Annotated[list[GenerationFieldAssignmentV2], Field(min_length=1, max_length=100)]


class GenerationNavigateEffectV2(StrictGenerationModel):
    kind: Literal["navigate"]
    target_page_key: TechnicalKey


class GenerationNotifyEffectV2(StrictGenerationModel):
    kind: Literal["notify"]
    level: Literal["info", "success", "warning", "error"]
    message: Annotated[str, Field(min_length=1, max_length=240)]


GenerationEffectV2 = Annotated[
    GenerationSetVariableEffectV2
    | GenerationValidateFormEffectV2
    | GenerationCreateEntityEffectV2
    | GenerationUpdateEntityEffectV2
    | GenerationNavigateEffectV2
    | GenerationNotifyEffectV2,
    Field(discriminator="kind"),
]


class GenerationTextViewBindingIntentV2(StrictGenerationModel):
    key: TechnicalKey
    page_key: TechnicalKey
    target: Literal["textContent"]
    value: GenerationExpressionV2


class GenerationVisibilityViewBindingIntentV2(StrictGenerationModel):
    key: TechnicalKey
    page_key: TechnicalKey
    target: Literal["visibility"]
    predicate: GenerationPredicateV2


class GenerationTableRowsViewBindingIntentV2(StrictGenerationModel):
    key: TechnicalKey
    page_key: TechnicalKey
    target: Literal["tableRows"]
    schema_key: TechnicalKey
    sort_field_key: TechnicalKey | None
    sort_direction: Literal["asc", "desc"]


GenerationViewBindingIntentV2 = Annotated[
    GenerationTextViewBindingIntentV2
    | GenerationVisibilityViewBindingIntentV2
    | GenerationTableRowsViewBindingIntentV2,
    Field(discriminator="target"),
]


class GenerationBehaviorIntentV2(StrictGenerationModel):
    key: TechnicalKey
    source_page_key: TechnicalKey
    guard: GenerationPredicateV2 | None
    effects: Annotated[list[GenerationEffectV2], Field(min_length=1, max_length=100)]
    guard_false_effects: Annotated[list[GenerationEffectV2], Field(max_length=100)]


class GenerationVariableValueIntentV2(StrictGenerationModel):
    variable_key: TechnicalKey
    value: GenerationRuntimeValueV2


class GenerationEntityFieldValueIntentV2(StrictGenerationModel):
    field_key: TechnicalKey
    value: GenerationRuntimeValueV2


class GenerationEntityFixtureV2(StrictGenerationModel):
    key: TechnicalKey
    fields: Annotated[list[GenerationEntityFieldValueIntentV2], Field(max_length=100)]


class GenerationEntitySetFixtureV2(StrictGenerationModel):
    schema_key: TechnicalKey
    entities: Annotated[list[GenerationEntityFixtureV2], Field(max_length=200)]


class GenerationCommitFormFieldStepV2(StrictGenerationModel):
    kind: Literal["commitFormField"]
    page_key: TechnicalKey
    form_key: TechnicalKey
    field_key: TechnicalKey
    value: GenerationStringValueV2 | GenerationIntegerValueV2
    expected_outcome: Literal["applied", "guard_false", "validation_failed"]


class GenerationActivateBehaviorStepV2(StrictGenerationModel):
    kind: Literal["activateBehavior"]
    behavior_intent_key: TechnicalKey
    expected_outcome: Literal["applied", "guard_false", "validation_failed"]


class GenerationActivateEntityBehaviorStepV2(StrictGenerationModel):
    kind: Literal["activateEntityBehavior"]
    behavior_intent_key: TechnicalKey
    schema_key: TechnicalKey
    entity_key: TechnicalKey
    expected_outcome: Literal["applied", "guard_false", "validation_failed"]


class GenerationSwitchRoleStepV2(StrictGenerationModel):
    kind: Literal["switchRole"]
    role_key: TechnicalKey
    expected_outcome: Literal["applied", "guard_false", "validation_failed"]


GenerationScenarioStepV2 = Annotated[
    GenerationCommitFormFieldStepV2
    | GenerationActivateBehaviorStepV2
    | GenerationActivateEntityBehaviorStepV2
    | GenerationSwitchRoleStepV2,
    Field(discriminator="kind"),
]


class GenerationScenarioMilestoneV2(StrictGenerationModel):
    after_step: Annotated[int, Field(ge=0, le=200)]
    current_page_key: TechnicalKey | None
    variable_values: Annotated[list[GenerationVariableValueIntentV2], Field(max_length=100)]
    entity_field_values: Annotated[
        list[GenerationScenarioEntityFieldExpectationV2], Field(max_length=100)
    ]


class GenerationScenarioEntityFieldExpectationV2(StrictGenerationModel):
    schema_key: TechnicalKey
    entity_key: TechnicalKey
    field_key: TechnicalKey
    value: GenerationRuntimeValueV2


class GenerationScenarioIntentV2(StrictGenerationModel):
    key: TechnicalKey
    actor_role_key: TechnicalKey
    start_page_key: TechnicalKey
    initial_variables: Annotated[list[GenerationVariableValueIntentV2], Field(max_length=100)]
    entity_fixtures: Annotated[list[GenerationEntitySetFixtureV2], Field(max_length=50)]
    allow_simulated_role_switch: bool
    scripted_steps: Annotated[list[GenerationScenarioStepV2], Field(max_length=200)]
    milestones: Annotated[list[GenerationScenarioMilestoneV2], Field(max_length=200)]

    @model_validator(mode="after")
    def validate_milestones(self) -> GenerationScenarioIntentV2:
        if any(milestone.after_step > len(self.scripted_steps) for milestone in self.milestones):
            raise ValueError("scenario milestone references a step beyond the script")
        _require_unique((str(item.after_step) for item in self.milestones), "milestone step")
        return self


type _GenerationExpressionType = tuple[str, str | None]


def _require_generation_value_type(
    value: GenerationRuntimeValueV2,
    expected_type: str,
    nullable: bool,
    label: str,
) -> None:
    if value.type == "null":
        if nullable or expected_type == "null":
            return
    elif value.type == expected_type:
        return
    raise ValueError(f"{label} value type must match {expected_type}")


def _generation_entity_ref_schema(
    expression: GenerationEntityRefExpressionV2,
    *,
    variables: dict[str, GenerationVariableIntentV2],
    allow_event_entity_ref: bool,
) -> str | None:
    if isinstance(expression, GenerationVariableExpressionV2):
        variable = variables.get(expression.variable_key)
        if variable is None:
            raise ValueError("blueprint expression variable must exist")
        if variable.value_type != "entityRef" or variable.entity_schema_key is None:
            raise ValueError("blueprint entity reference variable is invalid")
        return variable.entity_schema_key
    if isinstance(expression, GenerationEventEntityRefExpressionV2):
        if not allow_event_entity_ref:
            raise ValueError("blueprint expression cannot use an event entity here")
        return None
    raise AssertionError("generation entity-reference expression union is exhaustive")


def _generation_expression_type(
    expression: GenerationExpressionV2,
    *,
    variables: dict[str, GenerationVariableIntentV2],
    forms: dict[str, GenerationFormIntentV2],
    entity_fields: dict[str, dict[str, GenerationEntityFieldIntentV2]],
    allow_event_entity_ref: bool,
) -> _GenerationExpressionType:
    if isinstance(expression, GenerationLiteralExpressionV2):
        return expression.value.type, None
    if isinstance(expression, GenerationVariableExpressionV2):
        variable = variables.get(expression.variable_key)
        if variable is None:
            raise ValueError("blueprint expression variable must exist")
        return variable.value_type, variable.entity_schema_key
    if isinstance(expression, GenerationFormFieldExpressionV2):
        form = forms.get(expression.form_key)
        if form is None:
            raise ValueError("blueprint expression form must exist")
        form_field = next((item for item in form.fields if item.key == expression.field_key), None)
        if form_field is None:
            raise ValueError("blueprint expression form field must exist")
        return form_field.value_type, None
    if isinstance(expression, GenerationEventEntityRefExpressionV2):
        if not allow_event_entity_ref:
            raise ValueError("blueprint expression cannot use an event entity here")
        return "entityRef", None
    if isinstance(expression, GenerationEntityFieldExpressionV2):
        fields = entity_fields.get(expression.schema_key)
        if fields is None:
            raise ValueError("blueprint entity-field expression schema must exist")
        entity_field = fields.get(expression.field_key)
        if entity_field is None:
            raise ValueError("blueprint entity-field expression field must exist")
        entity_ref_schema = _generation_entity_ref_schema(
            expression.entity_ref,
            variables=variables,
            allow_event_entity_ref=allow_event_entity_ref,
        )
        if entity_ref_schema is not None and entity_ref_schema != expression.schema_key:
            raise ValueError("blueprint entity-field expression schema must match its entity ref")
        _require_generation_value_type(
            expression.fallback,
            entity_field.value_type,
            True,
            "blueprint entity-field fallback",
        )
        return entity_field.value_type, None
    raise AssertionError("generation expression union is exhaustive")


def _validate_generation_predicate(
    predicate: GenerationPredicateV2,
    *,
    role_keys: set[str],
    variables: dict[str, GenerationVariableIntentV2],
    forms: dict[str, GenerationFormIntentV2],
    entity_fields: dict[str, dict[str, GenerationEntityFieldIntentV2]],
    allow_event_entity_ref: bool,
) -> None:
    if isinstance(predicate, GenerationAllPredicateV2):
        for item in predicate.items:
            _validate_generation_predicate(
                item,
                role_keys=role_keys,
                variables=variables,
                forms=forms,
                entity_fields=entity_fields,
                allow_event_entity_ref=allow_event_entity_ref,
            )
        return
    if isinstance(predicate, GenerationRoleIsPredicateV2):
        if predicate.role_key not in role_keys:
            raise ValueError("blueprint predicate role must exist")
        return
    if isinstance(predicate, GenerationFormValidPredicateV2):
        if predicate.form_key not in forms:
            raise ValueError("blueprint predicate form must exist")
        return
    left_type, left_schema = _generation_expression_type(
        predicate.left,
        variables=variables,
        forms=forms,
        entity_fields=entity_fields,
        allow_event_entity_ref=allow_event_entity_ref,
    )
    right_type, right_schema = _generation_expression_type(
        predicate.right,
        variables=variables,
        forms=forms,
        entity_fields=entity_fields,
        allow_event_entity_ref=allow_event_entity_ref,
    )
    if left_type != "null" and right_type != "null" and left_type != right_type:
        raise ValueError("blueprint comparison expression types must match")
    if (
        left_type == "entityRef"
        and right_type == "entityRef"
        and left_schema is not None
        and right_schema is not None
        and left_schema != right_schema
    ):
        raise ValueError("blueprint comparison entity schemas must match")


def _validate_generation_effect(
    effect: GenerationEffectV2,
    *,
    page_keys: set[str],
    variables: dict[str, GenerationVariableIntentV2],
    forms: dict[str, GenerationFormIntentV2],
    entity_fields: dict[str, dict[str, GenerationEntityFieldIntentV2]],
    allow_event_entity_ref: bool,
) -> None:
    if isinstance(effect, GenerationSetVariableEffectV2):
        variable = variables.get(effect.variable_key)
        if variable is None:
            raise ValueError("blueprint set-variable target must exist")
        value_type, entity_schema_key = _generation_expression_type(
            effect.value,
            variables=variables,
            forms=forms,
            entity_fields=entity_fields,
            allow_event_entity_ref=allow_event_entity_ref,
        )
        if value_type != variable.value_type:
            raise ValueError("blueprint set-variable expression type must match its target")
        if (
            value_type == "entityRef"
            and entity_schema_key is not None
            and entity_schema_key != variable.entity_schema_key
        ):
            raise ValueError("blueprint set-variable entity schema must match its target")
        return
    if isinstance(effect, GenerationValidateFormEffectV2):
        if effect.form_key not in forms:
            raise ValueError("blueprint validate-form target must exist")
        return
    if isinstance(effect, GenerationNavigateEffectV2):
        if effect.target_page_key not in page_keys:
            raise ValueError("blueprint navigate target page must exist")
        return
    if isinstance(effect, GenerationNotifyEffectV2):
        return
    fields = entity_fields.get(effect.schema_key)
    if fields is None:
        raise ValueError("blueprint entity effect schema must exist")
    if isinstance(effect, GenerationCreateEntityEffectV2):
        result_variable = variables.get(effect.result_variable_key)
        if (
            result_variable is None
            or result_variable.value_type != "entityRef"
            or result_variable.entity_schema_key != effect.schema_key
        ):
            raise ValueError("blueprint create-entity result variable must match its schema")
        assignments = effect.values
        require_complete_fields = True
    else:
        entity_ref_schema = _generation_entity_ref_schema(
            effect.entity_ref,
            variables=variables,
            allow_event_entity_ref=allow_event_entity_ref,
        )
        if entity_ref_schema is not None and entity_ref_schema != effect.schema_key:
            raise ValueError("blueprint update-entity reference must match its schema")
        assignments = effect.updates
        require_complete_fields = False
    assignment_keys = _require_unique(
        (assignment.field_key for assignment in assignments),
        "entity effect field key",
    )
    if not assignment_keys.issubset(fields):
        raise ValueError("blueprint entity effect field must exist in its schema")
    if require_complete_fields and assignment_keys != set(fields):
        raise ValueError("blueprint create-entity fields must match its schema")
    for assignment in assignments:
        value_type, _ = _generation_expression_type(
            assignment.value,
            variables=variables,
            forms=forms,
            entity_fields=entity_fields,
            allow_event_entity_ref=allow_event_entity_ref,
        )
        if value_type != fields[assignment.field_key].value_type:
            raise ValueError("blueprint entity effect value type must match its field")


def _scenario_navigation_targets(behavior: GenerationBehaviorIntentV2) -> set[str]:
    return {
        effect.target_page_key
        for effect in (*behavior.effects, *behavior.guard_false_effects)
        if isinstance(effect, GenerationNavigateEffectV2)
    }


class GenerationBlueprintV1(StrictGenerationModel):
    contract_version: Literal[3]
    document_title: Annotated[str, Field(min_length=1, max_length=120)]
    product_intent: Annotated[str, Field(min_length=1, max_length=500)]
    output_locale: Literal["zh-CN", "en-US"]
    foundation_intent: GenerationFoundationIntentV1
    pages: Annotated[list[GenerationBlueprintPageV1], Field(min_length=1, max_length=20)]
    navigation: Annotated[list[GenerationBlueprintNavigationItemV1], Field(max_length=30)]
    flow_intents: Annotated[list[GenerationBlueprintFlowIntentV1], Field(max_length=30)]
    role_intents: Annotated[list[GenerationRoleIntentV2], Field(max_length=20)]
    entity_intents: Annotated[list[GenerationEntityIntentV2], Field(max_length=30)]
    variable_intents: Annotated[list[GenerationVariableIntentV2], Field(max_length=100)]
    form_intents: Annotated[list[GenerationFormIntentV2], Field(max_length=50)]
    view_binding_intents: Annotated[list[GenerationViewBindingIntentV2], Field(max_length=200)]
    behavior_intents: Annotated[list[GenerationBehaviorIntentV2], Field(max_length=100)]
    scenario_intents: Annotated[list[GenerationScenarioIntentV2], Field(max_length=30)]
    start_page_keys: Annotated[list[TechnicalKey], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def validate_references(self) -> GenerationBlueprintV1:
        page_keys = _require_unique((page.page_key for page in self.pages), "page key")
        _require_unique((page.route for page in self.pages), "page route")
        _require_unique((item.key for item in self.navigation), "navigation key")
        _require_unique((flow.key for flow in self.flow_intents), "flow key")
        role_keys = _require_unique((item.key for item in self.role_intents), "role intent")
        entity_keys = _require_unique((item.key for item in self.entity_intents), "entity intent")
        _require_unique((item.key for item in self.variable_intents), "variable intent")
        variables = {item.key: item for item in self.variable_intents}
        _require_unique((item.key for item in self.form_intents), "form intent")
        forms = {item.key: item for item in self.form_intents}
        _require_unique((item.key for item in self.view_binding_intents), "view-binding intent")
        _require_unique((item.key for item in self.behavior_intents), "behavior intent")
        behaviors = {item.key: item for item in self.behavior_intents}
        _require_unique(
            (f"{flow.behavior_intent_key}:{flow.target_page_key}" for flow in self.flow_intents),
            "flow behavior target",
        )
        _require_unique((item.key for item in self.scenario_intents), "scenario intent")
        _require_unique(self.start_page_keys, "start page key")
        entity_fields = {
            entity.key: {field.key: field for field in entity.fields}
            for entity in self.entity_intents
        }
        if not set(self.start_page_keys).issubset(page_keys):
            raise ValueError("blueprint start pages must exist")
        if any(item.target_page_key not in page_keys for item in self.navigation):
            raise ValueError("blueprint navigation target must exist")
        if any(
            flow.source_page_key not in page_keys or flow.target_page_key not in page_keys
            for flow in self.flow_intents
        ):
            raise ValueError("blueprint flow page must exist")
        if any(flow.behavior_intent_key not in behaviors for flow in self.flow_intents):
            raise ValueError("blueprint flow behavior must exist")
        if any(item.page_key not in page_keys for item in self.form_intents):
            raise ValueError("blueprint form page must exist")
        if any(item.page_key not in page_keys for item in self.view_binding_intents):
            raise ValueError("blueprint view-binding page must exist")
        behavior_pages = {item.key: item.source_page_key for item in self.behavior_intents}
        if any(page_key not in page_keys for page_key in behavior_pages.values()):
            raise ValueError("blueprint behavior source page must exist")
        if any(
            behavior_pages[flow.behavior_intent_key] != flow.source_page_key
            for flow in self.flow_intents
        ):
            raise ValueError("blueprint flow and behavior source pages must match")
        if any(
            variable.entity_schema_key is not None and variable.entity_schema_key not in entity_keys
            for variable in self.variable_intents
        ):
            raise ValueError("blueprint variable entity schema must exist")
        for binding in self.view_binding_intents:
            if isinstance(binding, GenerationTableRowsViewBindingIntentV2):
                fields = entity_fields.get(binding.schema_key)
                if fields is None:
                    raise ValueError("blueprint table binding schema must exist")
                if binding.sort_field_key is not None and binding.sort_field_key not in fields:
                    raise ValueError("blueprint table binding sort field must exist")
            elif isinstance(binding, GenerationTextViewBindingIntentV2):
                _generation_expression_type(
                    binding.value,
                    variables=variables,
                    forms=forms,
                    entity_fields=entity_fields,
                    allow_event_entity_ref=False,
                )
            else:
                _validate_generation_predicate(
                    binding.predicate,
                    role_keys=role_keys,
                    variables=variables,
                    forms=forms,
                    entity_fields=entity_fields,
                    allow_event_entity_ref=False,
                )
        for behavior in self.behavior_intents:
            if behavior.guard is not None:
                _validate_generation_predicate(
                    behavior.guard,
                    role_keys=role_keys,
                    variables=variables,
                    forms=forms,
                    entity_fields=entity_fields,
                    allow_event_entity_ref=True,
                )
            for effect in (*behavior.effects, *behavior.guard_false_effects):
                _validate_generation_effect(
                    effect,
                    page_keys=page_keys,
                    variables=variables,
                    forms=forms,
                    entity_fields=entity_fields,
                    allow_event_entity_ref=True,
                )
        flow_targets_by_behavior: dict[str, set[str]] = {}
        for flow in self.flow_intents:
            flow_targets_by_behavior.setdefault(flow.behavior_intent_key, set()).add(
                flow.target_page_key
            )
        for behavior in self.behavior_intents:
            navigation_targets = {
                effect.target_page_key
                for effect in (*behavior.effects, *behavior.guard_false_effects)
                if isinstance(effect, GenerationNavigateEffectV2)
            }
            if navigation_targets != flow_targets_by_behavior.get(behavior.key, set()):
                raise ValueError(
                    "blueprint flow targets must exactly match their behavior navigate targets"
                )
        for scenario in self.scenario_intents:
            if scenario.actor_role_key not in role_keys or scenario.start_page_key not in page_keys:
                raise ValueError("blueprint scenario role and start page must exist")
            _require_unique(
                (item.variable_key for item in scenario.initial_variables),
                "scenario initial variable",
            )
            for item in scenario.initial_variables:
                variable = variables.get(item.variable_key)
                if variable is None:
                    raise ValueError("blueprint scenario variable must exist")
                _require_generation_value_type(
                    item.value,
                    variable.value_type,
                    variable.nullable,
                    "blueprint scenario variable",
                )
            _require_unique(
                (item.schema_key for item in scenario.entity_fixtures),
                "scenario fixture schema",
            )
            fixture_entities: set[tuple[str, str]] = set()
            for entity_set in scenario.entity_fixtures:
                fields = entity_fields.get(entity_set.schema_key)
                if fields is None:
                    raise ValueError("blueprint scenario entity schema must exist")
                _require_unique(
                    (entity.key for entity in entity_set.entities),
                    "scenario fixture entity key",
                )
                for entity in entity_set.entities:
                    fixture_entities.add((entity_set.schema_key, entity.key))
                    fixture_field_keys = _require_unique(
                        (fixture_field.field_key for fixture_field in entity.fields),
                        "scenario fixture field key",
                    )
                    if fixture_field_keys != set(fields):
                        raise ValueError("blueprint scenario fixture fields must match its schema")
                    for fixture_field in entity.fields:
                        _require_generation_value_type(
                            fixture_field.value,
                            fields[fixture_field.field_key].value_type,
                            fields[fixture_field.field_key].nullable,
                            "blueprint scenario fixture field",
                        )
            possible_page_keys = {scenario.start_page_key}
            reachable_pages_after_step = [possible_page_keys]
            for step in scenario.scripted_steps:
                if isinstance(step, GenerationCommitFormFieldStepV2):
                    form = forms.get(step.form_key)
                    if step.page_key not in page_keys or form is None:
                        raise ValueError("scenario form step references an unknown page or form")
                    if form.page_key != step.page_key:
                        raise ValueError("scenario form step page must match its form intent")
                    if step.page_key not in possible_page_keys:
                        raise ValueError("scenario form step page must be currently reachable")
                    form_step_field = next(
                        (item for item in form.fields if item.key == step.field_key),
                        None,
                    )
                    if form_step_field is None:
                        raise ValueError("scenario form step field must exist")
                    _require_generation_value_type(
                        step.value,
                        form_step_field.value_type,
                        False,
                        "scenario form step",
                    )
                    possible_page_keys = {step.page_key}
                elif isinstance(
                    step,
                    (GenerationActivateBehaviorStepV2, GenerationActivateEntityBehaviorStepV2),
                ):
                    scenario_behavior = behaviors.get(step.behavior_intent_key)
                    if scenario_behavior is None:
                        raise ValueError("scenario behavior step references an unknown behavior")
                    if scenario_behavior.source_page_key not in possible_page_keys:
                        raise ValueError(
                            "scenario behavior source page must be currently reachable"
                        )
                    if isinstance(step, GenerationActivateEntityBehaviorStepV2):
                        if step.schema_key not in entity_fields:
                            raise ValueError("scenario entity behavior schema must exist")
                        if (step.schema_key, step.entity_key) not in fixture_entities:
                            raise ValueError(
                                "scenario entity behavior must reference an existing fixture"
                            )
                    navigation_targets = _scenario_navigation_targets(scenario_behavior)
                    possible_page_keys = navigation_targets or {scenario_behavior.source_page_key}
                elif isinstance(step, GenerationSwitchRoleStepV2):
                    if step.role_key not in role_keys:
                        raise ValueError("scenario role step references an unknown role")
                    if not scenario.allow_simulated_role_switch:
                        raise ValueError("scenario role step requires simulated role switching")
                reachable_pages_after_step.append(possible_page_keys)
            for milestone in scenario.milestones:
                if (
                    milestone.current_page_key is not None
                    and milestone.current_page_key not in page_keys
                ):
                    raise ValueError("scenario milestone page must exist")
                if (
                    milestone.current_page_key is not None
                    and milestone.current_page_key
                    not in reachable_pages_after_step[milestone.after_step]
                ):
                    raise ValueError("scenario milestone page must be reachable after its step")
                _require_unique(
                    (item.variable_key for item in milestone.variable_values),
                    "scenario milestone variable",
                )
                for milestone_variable in milestone.variable_values:
                    milestone_variable_definition = variables.get(milestone_variable.variable_key)
                    if milestone_variable_definition is None:
                        raise ValueError("scenario milestone variable must exist")
                    _require_generation_value_type(
                        milestone_variable.value,
                        milestone_variable_definition.value_type,
                        milestone_variable_definition.nullable,
                        "scenario milestone variable",
                    )
                _require_unique(
                    (
                        f"{item.schema_key}:{item.entity_key}:{item.field_key}"
                        for item in milestone.entity_field_values
                    ),
                    "scenario milestone entity field",
                )
                for milestone_entity_field in milestone.entity_field_values:
                    milestone_schema_fields = entity_fields.get(milestone_entity_field.schema_key)
                    if milestone_schema_fields is None:
                        raise ValueError("scenario milestone entity schema must exist")
                    if (
                        milestone_entity_field.schema_key,
                        milestone_entity_field.entity_key,
                    ) not in fixture_entities:
                        raise ValueError("scenario milestone entity fixture must exist")
                    milestone_field_definition = milestone_schema_fields.get(
                        milestone_entity_field.field_key
                    )
                    if milestone_field_definition is None:
                        raise ValueError("scenario milestone entity field must exist")
                    _require_generation_value_type(
                        milestone_entity_field.value,
                        milestone_field_definition.value_type,
                        milestone_field_definition.nullable,
                        "scenario milestone entity field",
                    )
        return self


class GenerationDesignTokenV1(StrictGenerationModel):
    key: TechnicalKey
    value: Annotated[str, Field(min_length=1, max_length=80)]


class GenerationSpacingTokenV1(StrictGenerationModel):
    key: TechnicalKey
    value: Annotated[
        str,
        Field(pattern=r"^(?:0|[1-9][0-9]*(?:\.[0-9]{1,4})?)(?:px|rem)$"),
    ]


class GenerationTopbarShellV3(StrictGenerationModel):
    kind: Literal["topbar"]
    title: Annotated[str, Field(min_length=1, max_length=80)]
    accent_color_token_key: TechnicalKey
    navigation_background_color_token_key: TechnicalKey
    content_background_color_token_key: TechnicalKey
    surface_color_token_key: TechnicalKey


class GenerationSidebarShellV3(StrictGenerationModel):
    kind: Literal["sidebar"]
    title: Annotated[str, Field(min_length=1, max_length=80)]
    accent_color_token_key: TechnicalKey
    navigation_background_color_token_key: TechnicalKey
    content_background_color_token_key: TechnicalKey
    surface_color_token_key: TechnicalKey
    navigation_width: Annotated[int, Field(ge=160, le=400)]
    expanded_min_width: Annotated[int, Field(ge=320, le=2560)]


GenerationSharedShellV3 = Annotated[
    GenerationSidebarShellV3 | GenerationTopbarShellV3,
    Field(discriminator="kind"),
]


class GenerationFoundationV1(StrictGenerationModel):
    contract_version: Literal[3]
    colors: Annotated[list[GenerationDesignTokenV1], Field(min_length=2, max_length=20)]
    spacing: Annotated[list[GenerationSpacingTokenV1], Field(min_length=1, max_length=20)]
    shared_shell: GenerationSharedShellV3
    content_conventions: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_foundation(self) -> GenerationFoundationV1:
        color_token_keys = _require_unique(
            (token.key for token in self.colors),
            "color token key",
        )
        _require_unique((token.key for token in self.spacing), "spacing token key")
        shell = self.shared_shell
        shell_color_token_keys = {
            shell.accent_color_token_key,
            shell.navigation_background_color_token_key,
            shell.content_background_color_token_key,
            shell.surface_color_token_key,
        }
        missing_shell_color_token_keys = shell_color_token_keys - color_token_keys
        if missing_shell_color_token_keys:
            missing = ", ".join(sorted(missing_shell_color_token_keys))
            raise ValueError(f"shared shell references unknown color token keys: {missing}")
        return self


class GeneratedNodeCommonV1(StrictGenerationModel):
    local_key: TechnicalKey
    name: Annotated[str, Field(min_length=1, max_length=80)]
    visibility: Literal["visible", "hidden"] = "visible"


class GeneratedStackNodeV1(GeneratedNodeCommonV1):
    type: Literal["Stack"]
    direction: Literal["row", "column"]
    gap: Annotated[int, Field(ge=0, le=48)]
    padding: Annotated[int, Field(ge=0, le=64)]
    children: Annotated[list[GeneratedNodeV1], Field(max_length=12)]


class GeneratedGridColumnOverrideV1(StrictGenerationModel):
    min_width: Annotated[int, Field(ge=320, le=2560)]
    columns: Annotated[int, Field(ge=1, le=12)]


class GeneratedGridNodeV1(GeneratedNodeCommonV1):
    type: Literal["Grid"]
    columns: Annotated[int, Field(ge=1, le=12)]
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: Annotated[int, Field(ge=0, le=256)]
    column_overrides: Annotated[list[GeneratedGridColumnOverrideV1], Field(max_length=3)]
    children: Annotated[list[GeneratedNodeV1], Field(max_length=12)]

    @model_validator(mode="after")
    def validate_column_overrides(self) -> GeneratedGridNodeV1:
        previous: int | None = None
        for item in self.column_overrides:
            if previous is not None and item.min_width <= previous:
                raise ValueError(
                    "grid column overrides must use strictly increasing minWidth values"
                )
            previous = item.min_width
        return self


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


class GeneratedTableCellV1(StrictGenerationModel):
    column_key: TechnicalKey
    value: Annotated[str, Field(max_length=500)]


class GeneratedTableRowV1(StrictGenerationModel):
    local_key: TechnicalKey
    cells: Annotated[list[GeneratedTableCellV1], Field(max_length=20)]

    @model_validator(mode="after")
    def validate_cells(self) -> GeneratedTableRowV1:
        _require_unique((cell.column_key for cell in self.cells), "table cell column key")
        return self


class GeneratedTableNodeV1(GeneratedNodeCommonV1):
    type: Literal["Table"]
    columns: Annotated[list[GeneratedTableColumnV1], Field(min_length=1, max_length=20)]
    rows: Annotated[
        list[GeneratedTableRowV1],
        Field(
            max_length=200,
            description=(
                "Static table rows as a native JSON array; use an empty array when "
                "the Table has a tableRows runtime binding"
            ),
        ),
    ]
    density: Literal["compact", "comfortable"]

    @model_validator(mode="after")
    def validate_table_shape(self) -> GeneratedTableNodeV1:
        column_keys = _require_unique(
            (column.key for column in self.columns),
            "table column key",
        )
        _require_unique((row.local_key for row in self.rows), "table row local key")
        for row in self.rows:
            if {cell.column_key for cell in row.cells} != column_keys:
                raise ValueError(f"table row {row.local_key} cells must match the table columns")
        return self


GeneratedNodeV1 = Annotated[
    GeneratedStackNodeV1
    | GeneratedGridNodeV1
    | GeneratedFormNodeV1
    | GeneratedTextNodeV1
    | GeneratedInputNodeV1
    | GeneratedButtonNodeV1
    | GeneratedTableNodeV1,
    Field(discriminator="type"),
]


class GeneratedFormFieldBindingV2(StrictGenerationModel):
    input_node_key: TechnicalKey
    field_key: TechnicalKey


class GeneratedFormBindingV2(StrictGenerationModel):
    form_node_key: TechnicalKey
    form_intent_key: TechnicalKey
    fields: Annotated[list[GeneratedFormFieldBindingV2], Field(max_length=100)]

    @model_validator(mode="after")
    def validate_fields(self) -> GeneratedFormBindingV2:
        _require_unique((field.input_node_key for field in self.fields), "form input node key")
        _require_unique((field.field_key for field in self.fields), "form field binding key")
        return self


class GeneratedViewBindingV2(StrictGenerationModel):
    node_key: TechnicalKey
    view_binding_intent_key: TechnicalKey


class GeneratedBehaviorBindingV2(StrictGenerationModel):
    source_node_key: TechnicalKey
    event: Literal["click", "submit", "rowActivated"]
    behavior_intent_key: TechnicalKey


class GeneratedPageV1(StrictGenerationModel):
    contract_version: Literal[3]
    page_key: TechnicalKey
    title: Annotated[str, Field(min_length=1, max_length=120)]
    route: Annotated[str, Field(pattern=r"^/[a-z0-9/-]*$", max_length=160)]
    root: GeneratedStackNodeV1
    form_bindings: Annotated[list[GeneratedFormBindingV2], Field(max_length=50)]
    view_bindings: Annotated[list[GeneratedViewBindingV2], Field(max_length=200)]
    behavior_bindings: Annotated[list[GeneratedBehaviorBindingV2], Field(max_length=100)]

    @model_validator(mode="after")
    def validate_local_keys(self) -> GeneratedPageV1:
        _collect_local_keys(self.root, set())
        if not _has_visible_generation_content(self.root):
            raise ValueError("generated page must contain at least one visible content node")
        _require_unique(
            (item.form_intent_key for item in self.form_bindings),
            "page form-binding intent key",
        )
        _require_unique(
            (item.view_binding_intent_key for item in self.view_bindings),
            "page view-binding intent key",
        )
        _require_unique(
            (item.behavior_intent_key for item in self.behavior_bindings),
            "page behavior-binding intent key",
        )
        return self


def _collect_local_keys(node: GeneratedNodeV1, seen: set[str]) -> None:
    if node.local_key in seen:
        raise ValueError(f"duplicate page node local key: {node.local_key}")
    seen.add(node.local_key)
    if isinstance(node, (GeneratedStackNodeV1, GeneratedGridNodeV1, GeneratedFormNodeV1)):
        for child in node.children:
            _collect_local_keys(child, seen)


def _has_visible_generation_content(node: GeneratedNodeV1) -> bool:
    if node.visibility != "visible":
        return False
    if isinstance(node, (GeneratedTextNodeV1, GeneratedInputNodeV1, GeneratedButtonNodeV1)):
        return True
    if isinstance(node, GeneratedTableNodeV1):
        return bool(node.columns)
    if isinstance(node, (GeneratedStackNodeV1, GeneratedGridNodeV1, GeneratedFormNodeV1)):
        return any(_has_visible_generation_content(child) for child in node.children)
    raise AssertionError("generation page node union is exhaustive")


class GenerationBlueprintEnvelopeV1(StrictGenerationModel):
    generation_contract_version: Literal[3]
    job_id: Annotated[str, Field(min_length=1, max_length=128)]
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    item_id: Annotated[str, Field(min_length=1, max_length=128)]
    task_kind: Literal["generation_blueprint"]
    context_object_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    payload: GenerationBlueprintV1


class GenerationFoundationEnvelopeV1(StrictGenerationModel):
    generation_contract_version: Literal[3]
    job_id: Annotated[str, Field(min_length=1, max_length=128)]
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    item_id: Annotated[str, Field(min_length=1, max_length=128)]
    task_kind: Literal["generation_foundation"]
    context_object_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    payload: GenerationFoundationV1


class GenerationPageEnvelopeV1(StrictGenerationModel):
    generation_contract_version: Literal[3]
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
