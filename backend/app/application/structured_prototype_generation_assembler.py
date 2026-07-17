from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID, uuid5

from pydantic import ValidationError

from app.application.structured_prototype_contracts import PrototypeDocumentV1
from app.application.structured_prototype_generation_contracts import (
    GeneratedBehaviorBindingV2,
    GeneratedButtonNodeV1,
    GeneratedFormBindingV2,
    GeneratedFormNodeV1,
    GeneratedGridNodeV1,
    GeneratedInputNodeV1,
    GeneratedNodeV1,
    GeneratedPageV1,
    GeneratedStackNodeV1,
    GeneratedTableNodeV1,
    GeneratedTextNodeV1,
    GeneratedViewBindingV2,
    GenerationActivateBehaviorStepV2,
    GenerationActivateEntityBehaviorStepV2,
    GenerationAllPredicateV2,
    GenerationBehaviorIntentV2,
    GenerationBlueprintV1,
    GenerationCommitFormFieldStepV2,
    GenerationComparePredicateV2,
    GenerationCreateEntityEffectV2,
    GenerationEffectV2,
    GenerationEntityFieldExpressionV2,
    GenerationEntityRefExpressionV2,
    GenerationEventEntityRefExpressionV2,
    GenerationExpressionV2,
    GenerationFormFieldExpressionV2,
    GenerationFormValidPredicateV2,
    GenerationFoundationV1,
    GenerationLiteralExpressionV2,
    GenerationNavigateEffectV2,
    GenerationNotifyEffectV2,
    GenerationPredicateV2,
    GenerationRoleIsPredicateV2,
    GenerationRuntimeValueV2,
    GenerationSetVariableEffectV2,
    GenerationSwitchRoleStepV2,
    GenerationTableRowsViewBindingIntentV2,
    GenerationTextViewBindingIntentV2,
    GenerationUpdateEntityEffectV2,
    GenerationValidateFormEffectV2,
    GenerationVariableExpressionV2,
    GenerationViewBindingIntentV2,
    GenerationVisibilityViewBindingIntentV2,
)

GENERATION_ASSEMBLER_VERSION = "structured-prototype-generic-assembler/v3"
GENERATION_ENTITY_NAMESPACE = UUID("add80290-85a3-50b4-97e3-ab2560b83177")
DEFAULT_RUNTIME_ROLE_KEY = "system-preview"
DEFAULT_RUNTIME_SCENARIO_KEY = "default-preview"


class StructuredPrototypeGenerationAssemblyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GenerationScenarioVariableExpectation(TypedDict):
    variableId: str
    value: dict[str, object]


class GenerationScenarioEntityFieldExpectation(TypedDict):
    schemaId: str
    entityId: str
    fieldId: str
    value: dict[str, object]


class GenerationScenarioMilestone(TypedDict):
    afterStep: int
    currentPageId: str | None
    variableValues: list[GenerationScenarioVariableExpectation]
    entityFieldValues: list[GenerationScenarioEntityFieldExpectation]


@dataclass(frozen=True, slots=True)
class GenerationScenarioValidationCase:
    scenario_key: str
    scenario_id: str
    batches: tuple[dict[str, object], ...]
    expected_outcomes: tuple[str, ...]
    milestones: tuple[GenerationScenarioMilestone, ...]


@dataclass(frozen=True, slots=True)
class _RuntimeIds:
    pages: Mapping[str, str]
    roles: Mapping[str, str]
    variables: Mapping[str, str]
    schemas: Mapping[str, str]
    entity_fields: Mapping[tuple[str, str], str]
    forms: Mapping[str, str]
    form_fields: Mapping[tuple[str, str], str]
    view_bindings: Mapping[str, str]
    behaviors: Mapping[str, str]
    scenarios: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _ResolvedPages:
    pages: Mapping[str, GeneratedPageV1]
    nodes: Mapping[str, Mapping[str, GeneratedNodeV1]]
    form_bindings: Mapping[str, tuple[str, GeneratedFormBindingV2]]
    view_bindings: Mapping[str, tuple[str, GeneratedViewBindingV2]]
    behavior_bindings: Mapping[str, tuple[str, GeneratedBehaviorBindingV2]]
    input_bindings: Mapping[tuple[str, str], tuple[str, str]]
    table_bindings: Mapping[tuple[str, str], str]


def generation_document_id(job_id: str) -> str:
    return str(uuid5(GENERATION_ENTITY_NAMESPACE, f"generation-document:{job_id}"))


def _entity_id(document_id: str, seed: str) -> str:
    try:
        namespace = UUID(document_id)
    except ValueError as exc:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_document_invalid",
            "generated document ID must be a UUID",
        ) from exc
    return str(uuid5(namespace, seed))


def generation_page_id(document_id: str, page_key: str) -> str:
    return _entity_id(document_id, f"page:{page_key}")


def generation_node_id(document_id: str, page_key: str, local_key: str) -> str:
    return _entity_id(document_id, f"node:{page_key}:{local_key}")


def generation_table_row_id(
    document_id: str,
    page_key: str,
    node_local_key: str,
    row_local_key: str,
) -> str:
    return _entity_id(
        document_id,
        f"table-row:{page_key}:{node_local_key}:{row_local_key}",
    )


def generation_scenario_id(document_id: str, scenario_key: str) -> str:
    return _entity_id(document_id, f"scenario:{scenario_key}")


def _lookup(mapping: Mapping[str, str], key: str, label: str) -> str:
    value = mapping.get(key)
    if value is None:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            f"{label} references unknown key {key}",
        )
    return value


def _lookup_pair(
    mapping: Mapping[tuple[str, str], str],
    first: str,
    second: str,
    label: str,
) -> str:
    value = mapping.get((first, second))
    if value is None:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            f"{label} references unknown key {first}.{second}",
        )
    return value


def _runtime_ids(document_id: str, blueprint: GenerationBlueprintV1) -> _RuntimeIds:
    role_keys = [item.key for item in blueprint.role_intents] or [DEFAULT_RUNTIME_ROLE_KEY]
    scenario_keys = [item.key for item in blueprint.scenario_intents] or [
        DEFAULT_RUNTIME_SCENARIO_KEY
    ]
    return _RuntimeIds(
        pages={
            page.page_key: generation_page_id(document_id, page.page_key)
            for page in blueprint.pages
        },
        roles={key: _entity_id(document_id, f"role:{key}") for key in role_keys},
        variables={
            item.key: _entity_id(document_id, f"variable:{item.key}")
            for item in blueprint.variable_intents
        },
        schemas={
            item.key: _entity_id(document_id, f"entity-schema:{item.key}")
            for item in blueprint.entity_intents
        },
        entity_fields={
            (schema.key, field.key): _entity_id(
                document_id,
                f"entity-field:{schema.key}:{field.key}",
            )
            for schema in blueprint.entity_intents
            for field in schema.fields
        },
        forms={
            item.key: _entity_id(document_id, f"form:{item.key}") for item in blueprint.form_intents
        },
        form_fields={
            (form.key, field.key): _entity_id(
                document_id,
                f"form-field:{form.key}:{field.key}",
            )
            for form in blueprint.form_intents
            for field in form.fields
        },
        view_bindings={
            item.key: _entity_id(document_id, f"view-binding:{item.key}")
            for item in blueprint.view_binding_intents
        },
        behaviors={
            item.key: _entity_id(document_id, f"behavior:{item.key}")
            for item in blueprint.behavior_intents
        },
        scenarios={key: generation_scenario_id(document_id, key) for key in scenario_keys},
    )


def validate_generation_blueprint(blueprint: GenerationBlueprintV1) -> None:
    behaviors = {behavior.key: behavior for behavior in blueprint.behavior_intents}
    flow_keys: set[str] = set()
    flow_targets: set[tuple[str, str]] = set()
    flow_targets_by_behavior: dict[str, set[str]] = {}
    for flow in blueprint.flow_intents:
        if flow.key in flow_keys:
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                f"flow key {flow.key} is duplicated",
            )
        flow_keys.add(flow.key)
        behavior = behaviors.get(flow.behavior_intent_key)
        if behavior is None:
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                f"flow {flow.key} references an unknown behavior intent",
            )
        if flow.source_page_key != behavior.source_page_key:
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                f"flow {flow.key} source page does not match its behavior intent",
            )
        behavior_target = (flow.behavior_intent_key, flow.target_page_key)
        if behavior_target in flow_targets:
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                "flow behavior and target page projection is duplicated",
            )
        flow_targets.add(behavior_target)
        flow_targets_by_behavior.setdefault(flow.behavior_intent_key, set()).add(
            flow.target_page_key
        )
    for behavior in blueprint.behavior_intents:
        navigation_targets = {
            effect.target_page_key
            for effect in (*behavior.effects, *behavior.guard_false_effects)
            if isinstance(effect, GenerationNavigateEffectV2)
        }
        if navigation_targets != flow_targets_by_behavior.get(behavior.key, set()):
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                "flow targets must exactly match their behavior navigate targets",
            )


def validate_generation_foundation(foundation: GenerationFoundationV1) -> None:
    del foundation


def _layout() -> dict[str, object]:
    auto = {"unit": "auto", "value": None}
    return {
        "width": auto,
        "minWidth": None,
        "maxWidth": None,
        "height": auto,
        "minHeight": None,
        "maxHeight": None,
        "grow": 0,
        "shrink": 1,
        "alignSelf": "stretch",
    }


def _walk_nodes(node: GeneratedNodeV1) -> Iterable[GeneratedNodeV1]:
    yield node
    if isinstance(node, (GeneratedStackNodeV1, GeneratedGridNodeV1, GeneratedFormNodeV1)):
        for child in node.children:
            yield from _walk_nodes(child)


def _resolve_pages(
    blueprint: GenerationBlueprintV1,
    pages: tuple[GeneratedPageV1, ...],
) -> _ResolvedPages:
    expected_order = tuple(page.page_key for page in blueprint.pages)
    if tuple(page.page_key for page in pages) != expected_order:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            "page artifacts must be supplied in confirmed blueprint order",
        )
    confirmed_pages = {page.page_key: page for page in blueprint.pages}
    page_map: dict[str, GeneratedPageV1] = {}
    nodes: dict[str, dict[str, GeneratedNodeV1]] = {}
    form_bindings: dict[str, tuple[str, GeneratedFormBindingV2]] = {}
    view_bindings: dict[str, tuple[str, GeneratedViewBindingV2]] = {}
    behavior_bindings: dict[str, tuple[str, GeneratedBehaviorBindingV2]] = {}
    input_bindings: dict[tuple[str, str], tuple[str, str]] = {}
    table_bindings: dict[tuple[str, str], str] = {}

    forms = {item.key: item for item in blueprint.form_intents}
    view_intents = {item.key: item for item in blueprint.view_binding_intents}
    behavior_intents = {item.key: item for item in blueprint.behavior_intents}
    entity_intents = {item.key: item for item in blueprint.entity_intents}
    for page in pages:
        confirmed = confirmed_pages[page.page_key]
        if page.title != confirmed.title or page.route != confirmed.route:
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                f"generated page {page.page_key} does not match its confirmed blueprint",
            )
        page_nodes = {node.local_key: node for node in _walk_nodes(page.root)}
        page_map[page.page_key] = page
        nodes[page.page_key] = page_nodes

        for form_binding in page.form_bindings:
            if form_binding.form_intent_key in form_bindings:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    f"form intent {form_binding.form_intent_key} is bound more than once",
                )
            form_intent = forms.get(form_binding.form_intent_key)
            form_node = page_nodes.get(form_binding.form_node_key)
            if form_intent is None or not isinstance(form_node, GeneratedFormNodeV1):
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "page form binding references an unknown form intent or Form node",
                )
            if form_node.form_key != form_binding.form_intent_key:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "generated Form key must match its explicit page binding",
                )
            if form_intent.page_key != page.page_key:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "page form binding does not match the confirmed form page",
                )
            descendants = {node.local_key: node for node in _walk_nodes(form_node)}
            bound_fields = {field.field_key for field in form_binding.fields}
            expected_fields = {field.key for field in form_intent.fields}
            if bound_fields != expected_fields:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    f"form {form_binding.form_intent_key} field bindings are incomplete",
                )
            field_intents = {field.key: field for field in form_intent.fields}
            for field in form_binding.fields:
                input_node = descendants.get(field.input_node_key)
                if not isinstance(input_node, GeneratedInputNodeV1):
                    raise StructuredPrototypeGenerationAssemblyError(
                        "generation_semantic_invalid",
                        "form field binding must reference a descendant Input node",
                    )
                expected_type = field_intents[field.field_key].value_type
                actual_type = "integer" if input_node.input_type == "number" else "string"
                if actual_type != expected_type:
                    raise StructuredPrototypeGenerationAssemblyError(
                        "generation_semantic_invalid",
                        "bound Input type does not match the confirmed form field",
                    )
                input_bindings[(page.page_key, field.input_node_key)] = (
                    form_binding.form_intent_key,
                    field.field_key,
                )
            form_bindings[form_binding.form_intent_key] = (page.page_key, form_binding)

        for view_binding in page.view_bindings:
            if view_binding.view_binding_intent_key in view_bindings:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    f"view-binding intent {view_binding.view_binding_intent_key} is bound more than once",
                )
            view_intent = view_intents.get(view_binding.view_binding_intent_key)
            node = page_nodes.get(view_binding.node_key)
            if view_intent is None or node is None:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "page view binding references an unknown intent or node",
                )
            if view_intent.page_key != page.page_key:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "page view binding does not match the confirmed binding page",
                )
            if isinstance(view_intent, GenerationTextViewBindingIntentV2) and not isinstance(
                node, GeneratedTextNodeV1
            ):
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "textContent view binding must target a Text node",
                )
            if isinstance(view_intent, GenerationTableRowsViewBindingIntentV2):
                if not isinstance(node, GeneratedTableNodeV1):
                    raise StructuredPrototypeGenerationAssemblyError(
                        "generation_semantic_invalid",
                        "tableRows view binding must target a Table node",
                    )
                if node.rows:
                    raise StructuredPrototypeGenerationAssemblyError(
                        "generation_semantic_invalid",
                        "generated Table with a tableRows binding cannot declare static rows",
                    )
                table_binding_key = (page.page_key, view_binding.node_key)
                if table_binding_key in table_bindings:
                    raise StructuredPrototypeGenerationAssemblyError(
                        "generation_semantic_invalid",
                        "generated Table node has more than one tableRows binding",
                    )
                table_bindings[table_binding_key] = view_intent.schema_key
            view_bindings[view_binding.view_binding_intent_key] = (page.page_key, view_binding)

        for behavior_binding in page.behavior_bindings:
            if behavior_binding.behavior_intent_key in behavior_bindings:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    f"behavior intent {behavior_binding.behavior_intent_key} is bound more than once",
                )
            node = page_nodes.get(behavior_binding.source_node_key)
            if node is None:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "page behavior binding references an unknown source node",
                )
            behavior_intent = behavior_intents.get(behavior_binding.behavior_intent_key)
            if behavior_intent is None or behavior_intent.source_page_key != page.page_key:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "page behavior binding does not match the confirmed source page",
                )
            if behavior_binding.event in {"click", "submit"} and not isinstance(
                node, GeneratedButtonNodeV1
            ):
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "click and submit behavior bindings must target a Button node",
                )
            if behavior_binding.event == "rowActivated" and not isinstance(
                node, GeneratedTableNodeV1
            ):
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    "rowActivated behavior binding must target a Table node",
                )
            behavior_bindings[behavior_binding.behavior_intent_key] = (
                page.page_key,
                behavior_binding,
            )

    if set(form_bindings) != set(forms):
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            "all confirmed form intents must be bound exactly once",
        )
    if set(view_bindings) != set(view_intents):
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            "all confirmed view-binding intents must be bound exactly once",
        )
    if set(behavior_bindings) != set(behavior_intents):
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            "all confirmed behavior intents must be bound exactly once",
        )
    for flow in blueprint.flow_intents:
        page_key, _ = behavior_bindings[flow.behavior_intent_key]
        if page_key != flow.source_page_key:
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                f"flow {flow.key} source page does not match its behavior binding",
            )
    for intent_key, (page_key, view_binding) in view_bindings.items():
        intent = view_intents[intent_key]
        if not isinstance(intent, GenerationTableRowsViewBindingIntentV2):
            continue
        node = nodes[page_key][view_binding.node_key]
        assert isinstance(node, GeneratedTableNodeV1)
        entity = entity_intents.get(intent.schema_key)
        if entity is None:
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                "tableRows binding references an unknown entity schema",
            )
        entity_fields = {field.key for field in entity.fields}
        if not {column.key for column in node.columns}.issubset(entity_fields):
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                "bound Table columns must reference fields from its entity schema",
            )
    return _ResolvedPages(
        pages=page_map,
        nodes=nodes,
        form_bindings=form_bindings,
        view_bindings=view_bindings,
        behavior_bindings=behavior_bindings,
        input_bindings=input_bindings,
        table_bindings=table_bindings,
    )


def _runtime_value(value: GenerationRuntimeValueV2) -> dict[str, object]:
    return value.model_dump(mode="json", by_alias=True)


def _compile_entity_ref(
    expression: GenerationEntityRefExpressionV2,
    ids: _RuntimeIds,
) -> dict[str, object]:
    if isinstance(expression, GenerationVariableExpressionV2):
        return {
            "kind": "variable",
            "variableId": _lookup(ids.variables, expression.variable_key, "variable expression"),
        }
    if isinstance(expression, GenerationEventEntityRefExpressionV2):
        return {"kind": "eventEntityRef"}
    raise AssertionError("generation entity-ref expression union is exhaustive")


def _compile_expression(
    expression: GenerationExpressionV2,
    ids: _RuntimeIds,
) -> dict[str, object]:
    if isinstance(expression, GenerationLiteralExpressionV2):
        return {"kind": "literal", "value": _runtime_value(expression.value)}
    if isinstance(expression, GenerationVariableExpressionV2):
        return {
            "kind": "variable",
            "variableId": _lookup(ids.variables, expression.variable_key, "variable expression"),
        }
    if isinstance(expression, GenerationFormFieldExpressionV2):
        return {
            "kind": "formField",
            "formId": _lookup(ids.forms, expression.form_key, "form-field expression"),
            "fieldId": _lookup_pair(
                ids.form_fields,
                expression.form_key,
                expression.field_key,
                "form-field expression",
            ),
        }
    if isinstance(expression, GenerationEventEntityRefExpressionV2):
        return {"kind": "eventEntityRef"}
    if isinstance(expression, GenerationEntityFieldExpressionV2):
        return {
            "kind": "entityField",
            "entityRef": _compile_entity_ref(expression.entity_ref, ids),
            "fieldId": _lookup_pair(
                ids.entity_fields,
                expression.schema_key,
                expression.field_key,
                "entity-field expression",
            ),
            "fallback": _runtime_value(expression.fallback),
        }
    raise AssertionError("generation expression union is exhaustive")


def _compile_predicate(
    predicate: GenerationPredicateV2,
    ids: _RuntimeIds,
) -> dict[str, object]:
    if isinstance(predicate, GenerationAllPredicateV2):
        return {
            "kind": "all",
            "items": [_compile_predicate(item, ids) for item in predicate.items],
        }
    if isinstance(predicate, GenerationRoleIsPredicateV2):
        return {
            "kind": "roleIs",
            "roleId": _lookup(ids.roles, predicate.role_key, "role predicate"),
        }
    if isinstance(predicate, GenerationFormValidPredicateV2):
        return {
            "kind": "formValid",
            "formId": _lookup(ids.forms, predicate.form_key, "form predicate"),
        }
    if isinstance(predicate, GenerationComparePredicateV2):
        return {
            "kind": "compare",
            "operator": predicate.operator,
            "left": _compile_expression(predicate.left, ids),
            "right": _compile_expression(predicate.right, ids),
        }
    raise AssertionError("generation predicate union is exhaustive")


def _compile_effect(effect: GenerationEffectV2, ids: _RuntimeIds) -> dict[str, object]:
    if isinstance(effect, GenerationSetVariableEffectV2):
        return {
            "kind": "setVariable",
            "variableId": _lookup(ids.variables, effect.variable_key, "set-variable effect"),
            "value": _compile_expression(effect.value, ids),
        }
    if isinstance(effect, GenerationValidateFormEffectV2):
        return {
            "kind": "validateForm",
            "formId": _lookup(ids.forms, effect.form_key, "validate-form effect"),
        }
    if isinstance(effect, GenerationCreateEntityEffectV2):
        return {
            "kind": "createEntity",
            "schemaId": _lookup(ids.schemas, effect.schema_key, "create-entity effect"),
            "resultVariableId": _lookup(
                ids.variables,
                effect.result_variable_key,
                "create-entity result variable",
            ),
            "values": [
                {
                    "fieldId": _lookup_pair(
                        ids.entity_fields,
                        effect.schema_key,
                        item.field_key,
                        "create-entity field",
                    ),
                    "value": _compile_expression(item.value, ids),
                }
                for item in effect.values
            ],
        }
    if isinstance(effect, GenerationUpdateEntityEffectV2):
        return {
            "kind": "updateEntity",
            "schemaId": _lookup(ids.schemas, effect.schema_key, "update-entity effect"),
            "entityRef": _compile_entity_ref(effect.entity_ref, ids),
            "updates": [
                {
                    "fieldId": _lookup_pair(
                        ids.entity_fields,
                        effect.schema_key,
                        item.field_key,
                        "update-entity field",
                    ),
                    "value": _compile_expression(item.value, ids),
                }
                for item in effect.updates
            ],
        }
    if isinstance(effect, GenerationNavigateEffectV2):
        return {
            "kind": "navigate",
            "targetPageId": _lookup(ids.pages, effect.target_page_key, "navigate effect"),
        }
    if isinstance(effect, GenerationNotifyEffectV2):
        return {
            "kind": "notify",
            "level": effect.level,
            "message": effect.message,
        }
    raise AssertionError("generation effect union is exhaustive")


def _common(document_id: str, page_key: str, node: GeneratedNodeV1) -> dict[str, object]:
    return {
        "id": generation_node_id(document_id, page_key, node.local_key),
        "name": node.name,
        "visibility": node.visibility,
        "layoutItem": _layout(),
        "responsive": [],
    }


def _convert_node(
    document_id: str,
    page_key: str,
    node: GeneratedNodeV1,
    resolved: _ResolvedPages,
    ids: _RuntimeIds,
) -> dict[str, object]:
    common = _common(document_id, page_key, node)
    if isinstance(node, GeneratedStackNodeV1):
        return {
            **common,
            "type": "Stack",
            "direction": node.direction,
            "gap": node.gap,
            "align": "stretch",
            "justify": "start",
            "padding": {
                "top": node.padding,
                "right": node.padding,
                "bottom": node.padding,
                "left": node.padding,
            },
            "children": [
                _convert_node(document_id, page_key, child, resolved, ids)
                for child in node.children
            ],
        }
    if isinstance(node, GeneratedGridNodeV1):
        return {
            **common,
            "type": "Grid",
            "columns": node.columns,
            "gap": node.gap,
            "padding": {
                "top": node.padding,
                "right": node.padding,
                "bottom": node.padding,
                "left": node.padding,
            },
            "columnOverrides": [
                item.model_dump(mode="json", by_alias=True)
                for item in node.column_overrides
            ],
            "children": [
                _convert_node(document_id, page_key, child, resolved, ids)
                for child in node.children
            ],
        }
    if isinstance(node, GeneratedFormNodeV1):
        return {
            **common,
            "type": "Form",
            "formDefinitionId": _lookup(ids.forms, node.form_key, "Form node"),
            "gap": node.gap,
            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "children": [
                _convert_node(document_id, page_key, child, resolved, ids)
                for child in node.children
            ],
        }
    if isinstance(node, GeneratedTextNodeV1):
        return {
            **common,
            "type": "Text",
            "content": node.content,
            "semantic": node.semantic,
            "tone": node.tone,
        }
    if isinstance(node, GeneratedInputNodeV1):
        binding = resolved.input_bindings.get((page_key, node.local_key))
        return {
            **common,
            "type": "Input",
            "label": node.label,
            "placeholder": node.placeholder,
            "value": "",
            "inputType": node.input_type,
            "required": node.required,
            "disabled": node.disabled,
            "formDefinitionId": (
                _lookup(ids.forms, binding[0], "Input form binding")
                if binding is not None
                else None
            ),
            "formFieldId": (
                _lookup_pair(ids.form_fields, binding[0], binding[1], "Input field binding")
                if binding is not None
                else None
            ),
        }
    if isinstance(node, GeneratedButtonNodeV1):
        return {
            **common,
            "type": "Button",
            "label": node.label,
            "variant": node.variant,
            "size": "medium",
            "disabled": node.disabled,
            "iconName": None,
        }
    if isinstance(node, GeneratedTableNodeV1):
        schema_key = resolved.table_bindings.get((page_key, node.local_key))
        return {
            **common,
            "type": "Table",
            "columns": [
                {
                    **column.model_dump(mode="json", by_alias=True),
                    "fieldId": (
                        _lookup_pair(
                            ids.entity_fields,
                            schema_key,
                            column.key,
                            "Table column binding",
                        )
                        if schema_key is not None
                        else None
                    ),
                }
                for column in node.columns
            ],
            "rows": [
                {
                    "id": generation_table_row_id(
                        document_id,
                        page_key,
                        node.local_key,
                        row.local_key,
                    ),
                    "cells": [cell.model_dump(mode="json", by_alias=True) for cell in row.cells],
                }
                for row in node.rows
            ],
            "density": node.density,
        }
    raise AssertionError("generation node union is exhaustive")


def _compile_view_binding(
    intent: GenerationViewBindingIntentV2,
    page_key: str,
    binding: GeneratedViewBindingV2,
    document_id: str,
    ids: _RuntimeIds,
) -> dict[str, object]:
    common = {
        "id": _lookup(ids.view_bindings, intent.key, "view binding"),
        "nodeId": generation_node_id(document_id, page_key, binding.node_key),
        "target": intent.target,
    }
    if isinstance(intent, GenerationTextViewBindingIntentV2):
        return {**common, "value": _compile_expression(intent.value, ids)}
    if isinstance(intent, GenerationVisibilityViewBindingIntentV2):
        return {**common, "predicate": _compile_predicate(intent.predicate, ids)}
    if isinstance(intent, GenerationTableRowsViewBindingIntentV2):
        return {
            **common,
            "schemaId": _lookup(ids.schemas, intent.schema_key, "tableRows binding"),
            "sortFieldId": (
                _lookup_pair(
                    ids.entity_fields,
                    intent.schema_key,
                    intent.sort_field_key,
                    "tableRows sort field",
                )
                if intent.sort_field_key is not None
                else None
            ),
            "sortDirection": intent.sort_direction,
        }
    raise AssertionError("generation view-binding union is exhaustive")


def _compile_behavior(
    intent: GenerationBehaviorIntentV2,
    page_key: str,
    binding: GeneratedBehaviorBindingV2,
    document_id: str,
    ids: _RuntimeIds,
) -> dict[str, object]:
    return {
        "id": _lookup(ids.behaviors, intent.key, "behavior"),
        "key": intent.key,
        "enabled": True,
        "trigger": {
            "kind": "nodeEvent",
            "nodeId": generation_node_id(document_id, page_key, binding.source_node_key),
            "event": binding.event,
        },
        "guard": _compile_predicate(intent.guard, ids) if intent.guard is not None else None,
        "effects": [_compile_effect(effect, ids) for effect in intent.effects],
        "guardFalseEffects": [
            _compile_effect(effect, ids) for effect in intent.guard_false_effects
        ],
    }


def _runtime_payload(
    document_id: str,
    blueprint: GenerationBlueprintV1,
    resolved: _ResolvedPages,
    ids: _RuntimeIds,
) -> dict[str, object]:
    roles = (
        [
            {
                "id": _lookup(ids.roles, item.key, "role"),
                "key": item.key,
                "label": item.label,
            }
            for item in blueprint.role_intents
        ]
        if blueprint.role_intents
        else [
            {
                "id": ids.roles[DEFAULT_RUNTIME_ROLE_KEY],
                "key": DEFAULT_RUNTIME_ROLE_KEY,
                "label": "System preview",
            }
        ]
    )
    entity_schemas = [
        {
            "id": _lookup(ids.schemas, schema.key, "entity schema"),
            "key": schema.key,
            "fields": [
                {
                    "id": _lookup_pair(
                        ids.entity_fields,
                        schema.key,
                        field.key,
                        "entity field",
                    ),
                    "key": field.key,
                    "valueType": field.value_type,
                    "nullable": field.nullable,
                }
                for field in schema.fields
            ],
        }
        for schema in blueprint.entity_intents
    ]
    forms = [
        {
            "id": _lookup(ids.forms, form.key, "runtime form"),
            "key": form.key,
            "fields": [
                {
                    "id": _lookup_pair(
                        ids.form_fields,
                        form.key,
                        field.key,
                        "runtime form field",
                    ),
                    "key": field.key,
                    "valueType": field.value_type,
                    "initialValue": _runtime_value(field.initial_value),
                    "required": field.required,
                    "minInteger": field.min_integer,
                }
                for field in form.fields
            ],
        }
        for form in blueprint.form_intents
    ]
    view_intents = {item.key: item for item in blueprint.view_binding_intents}
    view_bindings = [
        _compile_view_binding(
            view_intents[key],
            page_key,
            binding,
            document_id,
            ids,
        )
        for key, (page_key, binding) in resolved.view_bindings.items()
    ]
    behavior_intents = {item.key: item for item in blueprint.behavior_intents}
    rules = [
        _compile_behavior(
            behavior_intents[key],
            page_key,
            binding,
            document_id,
            ids,
        )
        for key, (page_key, binding) in resolved.behavior_bindings.items()
    ]
    scenarios = []
    for scenario in blueprint.scenario_intents:
        entity_fixtures = []
        for entity_set in scenario.entity_fixtures:
            entity_fixtures.append(
                {
                    "schemaId": _lookup(ids.schemas, entity_set.schema_key, "scenario schema"),
                    "entities": [
                        {
                            "id": _entity_id(
                                document_id,
                                f"scenario-entity:{scenario.key}:{entity_set.schema_key}:{entity.key}",
                            ),
                            "schemaId": _lookup(
                                ids.schemas,
                                entity_set.schema_key,
                                "scenario entity schema",
                            ),
                            "fields": [
                                {
                                    "fieldId": _lookup_pair(
                                        ids.entity_fields,
                                        entity_set.schema_key,
                                        field.field_key,
                                        "scenario entity field",
                                    ),
                                    "value": _runtime_value(field.value),
                                }
                                for field in entity.fields
                            ],
                        }
                        for entity in entity_set.entities
                    ],
                }
            )
        scenarios.append(
            {
                "id": _lookup(ids.scenarios, scenario.key, "scenario"),
                "key": scenario.key,
                "actorRoleId": _lookup(ids.roles, scenario.actor_role_key, "scenario role"),
                "startPageId": _lookup(ids.pages, scenario.start_page_key, "scenario page"),
                "initialVariables": [
                    {
                        "variableId": _lookup(
                            ids.variables,
                            item.variable_key,
                            "scenario variable",
                        ),
                        "value": _runtime_value(item.value),
                    }
                    for item in scenario.initial_variables
                ],
                "entityFixtures": entity_fixtures,
                "allowSimulatedRoleSwitch": scenario.allow_simulated_role_switch,
            }
        )
    if not scenarios:
        preview_role_key = (
            blueprint.role_intents[0].key if blueprint.role_intents else DEFAULT_RUNTIME_ROLE_KEY
        )
        scenarios.append(
            {
                "id": ids.scenarios[DEFAULT_RUNTIME_SCENARIO_KEY],
                "key": DEFAULT_RUNTIME_SCENARIO_KEY,
                "actorRoleId": _lookup(ids.roles, preview_role_key, "default scenario role"),
                "startPageId": ids.pages[blueprint.start_page_keys[0]],
                "initialVariables": [],
                "entityFixtures": [],
                "allowSimulatedRoleSwitch": False,
            }
        )
    return {
        "runtimeSchemaVersion": 1,
        "pageIds": [ids.pages[page.page_key] for page in blueprint.pages],
        "roles": roles,
        "variables": [
            {
                "id": _lookup(ids.variables, variable.key, "runtime variable"),
                "key": variable.key,
                "valueType": variable.value_type,
                "nullable": variable.nullable,
                "entitySchemaId": (
                    _lookup(
                        ids.schemas,
                        variable.entity_schema_key,
                        "runtime variable entity schema",
                    )
                    if variable.entity_schema_key is not None
                    else None
                ),
                "defaultValue": _runtime_value(variable.default_value),
            }
            for variable in blueprint.variable_intents
        ],
        "entitySchemas": entity_schemas,
        "forms": forms,
        "viewBindings": view_bindings,
        "rules": rules,
        "scenarios": scenarios,
    }


def generation_validation_cases(
    *,
    document_id: str,
    blueprint: GenerationBlueprintV1,
    pages: tuple[GeneratedPageV1, ...],
) -> tuple[GenerationScenarioValidationCase, ...]:
    resolved = _resolve_pages(blueprint, pages)
    ids = _runtime_ids(document_id, blueprint)
    cases: list[GenerationScenarioValidationCase] = []
    for scenario in blueprint.scenario_intents:
        batches: list[dict[str, object]] = []
        outcomes: list[str] = []
        fixture_ids = {
            (entity_set.schema_key, entity.key): _entity_id(
                document_id,
                f"scenario-entity:{scenario.key}:{entity_set.schema_key}:{entity.key}",
            )
            for entity_set in scenario.entity_fixtures
            for entity in entity_set.entities
        }
        for index, step in enumerate(scenario.scripted_steps):
            if isinstance(step, GenerationCommitFormFieldStepV2):
                page_key, form_binding = resolved.form_bindings[step.form_key]
                if page_key != step.page_key:
                    raise StructuredPrototypeGenerationAssemblyError(
                        "generation_semantic_invalid",
                        "scenario form step page does not match its page binding",
                    )
                input_key = next(
                    field.input_node_key
                    for field in form_binding.fields
                    if field.field_key == step.field_key
                )
                event: dict[str, object] = {
                    "kind": "fieldValueCommitted",
                    "nodeId": generation_node_id(document_id, page_key, input_key),
                    "formId": ids.forms[step.form_key],
                    "fieldId": ids.form_fields[(step.form_key, step.field_key)],
                    "value": _runtime_value(step.value),
                }
            elif isinstance(
                step,
                (GenerationActivateBehaviorStepV2, GenerationActivateEntityBehaviorStepV2),
            ):
                page_key, behavior_binding = resolved.behavior_bindings[step.behavior_intent_key]
                node_id = generation_node_id(
                    document_id,
                    page_key,
                    behavior_binding.source_node_key,
                )
                if isinstance(step, GenerationActivateEntityBehaviorStepV2):
                    if behavior_binding.event != "rowActivated":
                        raise StructuredPrototypeGenerationAssemblyError(
                            "generation_semantic_invalid",
                            "entity behavior step requires a rowActivated binding",
                        )
                    entity_id = fixture_ids.get((step.schema_key, step.entity_key))
                    if entity_id is None:
                        raise StructuredPrototypeGenerationAssemblyError(
                            "generation_semantic_invalid",
                            "entity behavior step references an unknown scenario fixture",
                        )
                    event = {
                        "kind": "tableRowActivated",
                        "nodeId": node_id,
                        "entityRef": {
                            "type": "entityRef",
                            "schemaId": ids.schemas[step.schema_key],
                            "entityId": entity_id,
                        },
                    }
                else:
                    if behavior_binding.event == "rowActivated":
                        raise StructuredPrototypeGenerationAssemblyError(
                            "generation_semantic_invalid",
                            "rowActivated scenario step must identify an entity fixture",
                        )
                    event = {
                        "kind": "nodeActivated",
                        "nodeId": node_id,
                        "event": behavior_binding.event,
                    }
            elif isinstance(step, GenerationSwitchRoleStepV2):
                event = {
                    "kind": "switchSimulatedRole",
                    "roleId": ids.roles[step.role_key],
                }
            else:
                raise AssertionError("generation scenario step union is exhaustive")
            batches.append(
                {
                    "clientEventId": f"{scenario.key}:{index + 1}",
                    "expectedSequenceNo": index,
                    "events": [event],
                }
            )
            outcomes.append(step.expected_outcome)
        milestones: list[GenerationScenarioMilestone] = []
        for milestone in scenario.milestones:
            milestones.append(
                {
                    "afterStep": milestone.after_step,
                    "currentPageId": (
                        ids.pages[milestone.current_page_key]
                        if milestone.current_page_key is not None
                        else None
                    ),
                    "variableValues": [
                        {
                            "variableId": ids.variables[item.variable_key],
                            "value": _runtime_value(item.value),
                        }
                        for item in milestone.variable_values
                    ],
                    "entityFieldValues": [
                        {
                            "schemaId": ids.schemas[item.schema_key],
                            "entityId": fixture_ids[(item.schema_key, item.entity_key)],
                            "fieldId": ids.entity_fields[(item.schema_key, item.field_key)],
                            "value": _runtime_value(item.value),
                        }
                        for item in milestone.entity_field_values
                    ],
                }
            )
        cases.append(
            GenerationScenarioValidationCase(
                scenario_key=scenario.key,
                scenario_id=ids.scenarios[scenario.key],
                batches=tuple(batches),
                expected_outcomes=tuple(outcomes),
                milestones=tuple(milestones),
            )
        )
    if not cases:
        cases.append(
            GenerationScenarioValidationCase(
                scenario_key=DEFAULT_RUNTIME_SCENARIO_KEY,
                scenario_id=ids.scenarios[DEFAULT_RUNTIME_SCENARIO_KEY],
                batches=(),
                expected_outcomes=(),
                milestones=(),
            )
        )
    return tuple(cases)


def assemble_generation_candidate(
    *,
    document_id: str,
    blueprint: GenerationBlueprintV1,
    foundation: GenerationFoundationV1,
    pages: tuple[GeneratedPageV1, ...],
) -> PrototypeDocumentV1:
    validate_generation_blueprint(blueprint)
    validate_generation_foundation(foundation)
    resolved = _resolve_pages(blueprint, pages)
    ids = _runtime_ids(document_id, blueprint)
    payload = {
        "schemaVersion": 1,
        "id": document_id,
        "title": blueprint.document_title,
        "locale": blueprint.output_locale,
        "settings": {
            "defaultViewport": "desktop",
            "theme": "system",
            "shell": foundation.shared_shell.model_dump(mode="json", by_alias=True),
        },
        "tokens": {
            "colors": [token.model_dump(mode="json", by_alias=True) for token in foundation.colors],
            "spacing": [
                token.model_dump(mode="json", by_alias=True) for token in foundation.spacing
            ],
        },
        "componentDefinitions": [],
        "pages": [
            {
                "id": ids.pages[page.page_key],
                "key": page.page_key,
                "title": page.title,
                "route": page.route,
                "viewport": {"width": 1440, "height": 900},
                "root": _convert_node(
                    document_id,
                    page.page_key,
                    resolved.pages[page.page_key].root,
                    resolved,
                    ids,
                ),
            }
            for page in blueprint.pages
        ],
        "navigation": {
            "items": [
                {
                    "id": _entity_id(document_id, f"navigation:{item.key}"),
                    "key": item.key,
                    "label": item.label,
                    "targetPageId": ids.pages[item.target_page_key],
                }
                for item in blueprint.navigation
            ]
        },
        "flows": [
            {
                "id": _entity_id(document_id, f"flow:{flow.key}"),
                "key": flow.key,
                "ruleId": ids.behaviors[flow.behavior_intent_key],
                "fromNodeId": generation_node_id(
                    document_id,
                    flow.source_page_key,
                    resolved.behavior_bindings[flow.behavior_intent_key][1].source_node_key,
                ),
                "toPageId": ids.pages[flow.target_page_key],
            }
            for flow in blueprint.flow_intents
        ],
        "runtime": _runtime_payload(document_id, blueprint, resolved, ids),
        "assetRefs": [],
    }
    try:
        return PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_document_invalid",
            "assembled generated document does not satisfy the canonical contract",
        ) from exc
