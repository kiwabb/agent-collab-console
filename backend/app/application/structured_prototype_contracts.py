from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.adapters.prototype_object_store import canonical_json_bytes

DOCUMENT_SCHEMA_VERSION: Literal[1] = 1
COMMAND_CONTRACT_VERSION: Literal[1] = 1
PROTOTYPE_ENTITY_NAMESPACE = UUID("40a604ef-4769-5b60-9562-9cd0d9bfcbbd")

TECHNICAL_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
ROUTE_RE = re.compile(r"^/(?:[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*)?$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _camel_alias(field_name: str) -> str:
    head, *tail = field_name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class StrictPrototypeModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_alias,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
        str_strip_whitespace=False,
    )


class StructuredPrototypeContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("entity ID must be a UUID") from exc
    if str(parsed) != value:
        raise ValueError("entity ID must use canonical lowercase UUID form")
    return value


type EntityId = Annotated[
    str,
    Field(min_length=36, max_length=36, pattern=r"^[0-9a-f-]+$"),
    AfterValidator(_canonical_uuid),
]
type TechnicalKey = Annotated[str, Field(pattern=TECHNICAL_KEY_RE.pattern)]
type Sha256 = Annotated[str, Field(pattern=SHA256_RE.pattern)]


class LengthV1(StrictPrototypeModel):
    unit: Literal["px", "percent", "rem", "auto"]
    value: str | None

    @model_validator(mode="after")
    def validate_value(self) -> LengthV1:
        if self.unit == "auto":
            if self.value is not None:
                raise ValueError("auto length must use a null value")
            return self
        if (
            self.value is None
            or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?", self.value) is None
        ):
            raise ValueError("length value must be a canonical non-negative decimal string")
        numeric = float(self.value)
        if self.unit == "percent" and numeric > 100:
            raise ValueError("percentage length must not exceed 100")
        if self.unit == "px" and numeric > 4096:
            raise ValueError("pixel length must not exceed 4096")
        if self.unit == "rem" and numeric > 256:
            raise ValueError("rem length must not exceed 256")
        return self


class LayoutItemV1(StrictPrototypeModel):
    width: LengthV1
    min_width: LengthV1 | None
    max_width: LengthV1 | None
    height: LengthV1
    min_height: LengthV1 | None
    max_height: LengthV1 | None
    grow: Annotated[int, Field(ge=0, le=12)]
    shrink: Annotated[int, Field(ge=0, le=12)]
    align_self: Literal["auto", "start", "center", "end", "stretch"]


class LayoutItemUpdateV1(StrictPrototypeModel):
    width: LengthV1 | None = None
    min_width: LengthV1 | None = None
    max_width: LengthV1 | None = None
    height: LengthV1 | None = None
    min_height: LengthV1 | None = None
    max_height: LengthV1 | None = None
    grow: Annotated[int | None, Field(ge=0, le=12)] = None
    shrink: Annotated[int | None, Field(ge=0, le=12)] = None
    align_self: Literal["auto", "start", "center", "end", "stretch"] | None = None

    @model_validator(mode="after")
    def require_update(self) -> LayoutItemUpdateV1:
        if not self.model_fields_set:
            raise ValueError("layout update must contain at least one field")
        for field_name in {
            "width",
            "height",
            "grow",
            "shrink",
            "align_self",
        } & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"layout update field {field_name} cannot be null")
        return self


class ResponsiveOverrideV1(StrictPrototypeModel):
    breakpoint: Literal["sm", "md", "lg"]
    layout_item: LayoutItemUpdateV1


class PaddingV1(StrictPrototypeModel):
    top: Annotated[int, Field(ge=0, le=256)]
    right: Annotated[int, Field(ge=0, le=256)]
    bottom: Annotated[int, Field(ge=0, le=256)]
    left: Annotated[int, Field(ge=0, le=256)]


class NodeCommonV1(StrictPrototypeModel):
    id: EntityId
    name: Annotated[str, Field(min_length=1, max_length=80)]
    visibility: Literal["visible", "hidden"]
    layout_item: LayoutItemV1
    responsive: Annotated[list[ResponsiveOverrideV1], Field(max_length=3)]

    @model_validator(mode="after")
    def validate_responsive_overrides(self) -> NodeCommonV1:
        _unique((item.breakpoint for item in self.responsive), "responsive breakpoint")
        return self


class TableColumnV1(StrictPrototypeModel):
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=80)]


class TableCellV1(StrictPrototypeModel):
    column_key: TechnicalKey
    value: Annotated[str, Field(max_length=500)]


class TableRowV1(StrictPrototypeModel):
    id: EntityId
    cells: Annotated[list[TableCellV1], Field(max_length=30)]


class StackNodeV1(NodeCommonV1):
    type: Literal["Stack"]
    direction: Literal["row", "column"]
    gap: Annotated[int, Field(ge=0, le=128)]
    align: Literal["start", "center", "end", "stretch"]
    justify: Literal["start", "center", "end", "between"]
    padding: PaddingV1
    children: Annotated[list[UINodeV1], Field(max_length=500)]


class FormNodeV1(NodeCommonV1):
    type: Literal["Form"]
    form_definition_id: EntityId
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: PaddingV1
    children: Annotated[list[UINodeV1], Field(min_length=1, max_length=200)]


class TextNodeV1(NodeCommonV1):
    type: Literal["Text"]
    content: Annotated[str, Field(max_length=8_000)]
    semantic: Literal["heading", "body", "label", "caption"]
    tone: Literal["default", "muted", "success", "warning", "danger"]


class InputNodeV1(NodeCommonV1):
    type: Literal["Input"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    placeholder: Annotated[str, Field(max_length=240)]
    value: Annotated[str, Field(max_length=8_000)]
    input_type: Literal["text", "number", "email"]
    required: bool
    disabled: bool


class ButtonNodeV1(NodeCommonV1):
    type: Literal["Button"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    variant: Literal["primary", "secondary", "danger", "ghost"]
    size: Literal["small", "medium", "large"]
    disabled: bool
    icon_name: Annotated[str, Field(min_length=1, max_length=80)] | None


class TableNodeV1(NodeCommonV1):
    type: Literal["Table"]
    columns: Annotated[list[TableColumnV1], Field(min_length=1, max_length=30)]
    rows: Annotated[list[TableRowV1], Field(max_length=200)]
    density: Literal["compact", "comfortable"]

    @model_validator(mode="after")
    def validate_table_shape(self) -> TableNodeV1:
        column_keys = _unique((column.key for column in self.columns), "table column key")
        _unique((row.id for row in self.rows), "table row ID")
        for row in self.rows:
            cell_keys = _unique((cell.column_key for cell in row.cells), "table cell column key")
            if cell_keys != column_keys:
                raise ValueError(f"table row {row.id} cells must match the table columns")
        return self


type UINodeV1 = Annotated[
    StackNodeV1 | FormNodeV1 | TextNodeV1 | InputNodeV1 | ButtonNodeV1 | TableNodeV1,
    Field(discriminator="type"),
]


class ViewportSettingsV1(StrictPrototypeModel):
    width: Annotated[int, Field(ge=320, le=2560)]
    height: Annotated[int, Field(ge=480, le=2160)]


class PrototypePageV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    title: Annotated[str, Field(min_length=1, max_length=80)]
    route: Annotated[str, Field(pattern=ROUTE_RE.pattern, max_length=240)]
    viewport: ViewportSettingsV1
    root: UINodeV1


class PrototypeSettingsV1(StrictPrototypeModel):
    default_viewport: Literal["desktop", "tablet", "mobile"]
    theme: Literal["light", "dark", "system"]


class DesignTokenV1(StrictPrototypeModel):
    key: TechnicalKey
    value: Annotated[str, Field(min_length=1, max_length=120)]


class DesignTokensV1(StrictPrototypeModel):
    colors: Annotated[list[DesignTokenV1], Field(max_length=100)]
    spacing: Annotated[list[DesignTokenV1], Field(max_length=50)]


class ComponentDefinitionV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    root: UINodeV1


class NavigationItemV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=80)]
    target_page_id: EntityId


class NavigationDefinitionV1(StrictPrototypeModel):
    items: Annotated[list[NavigationItemV1], Field(max_length=20)]


class PrototypeFlowV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    rule_id: EntityId
    from_node_id: EntityId
    to_page_id: EntityId | None


class AssetRefV1(StrictPrototypeModel):
    id: EntityId
    content_hash: Sha256
    media_type: Literal["image/png", "image/jpeg", "image/webp", "image/svg+xml"]
    alt: Annotated[str, Field(max_length=240)]


class NullRuntimeValueV1(StrictPrototypeModel):
    type: Literal["null"]


class BooleanRuntimeValueV1(StrictPrototypeModel):
    type: Literal["boolean"]
    value: bool


class IntegerRuntimeValueV1(StrictPrototypeModel):
    type: Literal["integer"]
    value: int


class StringRuntimeValueV1(StrictPrototypeModel):
    type: Literal["string"]
    value: Annotated[str, Field(max_length=8_000)]


class EnumRuntimeValueV1(StrictPrototypeModel):
    type: Literal["enum"]
    value: TechnicalKey


class EntityRefRuntimeValueV1(StrictPrototypeModel):
    type: Literal["entityRef"]
    schema_id: EntityId
    entity_id: EntityId


type RuntimeValueV1 = Annotated[
    NullRuntimeValueV1
    | BooleanRuntimeValueV1
    | IntegerRuntimeValueV1
    | StringRuntimeValueV1
    | EnumRuntimeValueV1
    | EntityRefRuntimeValueV1,
    Field(discriminator="type"),
]


class RuntimeRoleV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=80)]


class RuntimeVariableV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    value_type: Literal["null", "boolean", "integer", "string", "enum", "entityRef"]
    nullable: bool
    default_value: RuntimeValueV1


class RuntimeEntityFieldV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    value_type: Literal["null", "boolean", "integer", "string", "enum", "entityRef"]
    nullable: bool


class RuntimeEntitySchemaV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    fields: Annotated[list[RuntimeEntityFieldV1], Field(max_length=100)]


class RuntimeFormFieldV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    value_type: Literal["string", "integer"]
    initial_value: StringRuntimeValueV1 | IntegerRuntimeValueV1
    required: bool
    min_integer: int | None


class RuntimeFormV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    fields: Annotated[list[RuntimeFormFieldV1], Field(max_length=100)]


class LiteralExpressionV1(StrictPrototypeModel):
    kind: Literal["literal"]
    value: RuntimeValueV1


class VariableExpressionV1(StrictPrototypeModel):
    kind: Literal["variable"]
    variable_id: EntityId


class FormFieldExpressionV1(StrictPrototypeModel):
    kind: Literal["formField"]
    form_id: EntityId
    field_id: EntityId


class EventEntityRefExpressionV1(StrictPrototypeModel):
    kind: Literal["eventEntityRef"]


class EntityFieldExpressionV1(StrictPrototypeModel):
    kind: Literal["entityField"]
    entity_ref: VariableExpressionV1 | EventEntityRefExpressionV1
    field_id: EntityId
    fallback: RuntimeValueV1


type RuntimeExpressionV1 = Annotated[
    LiteralExpressionV1
    | VariableExpressionV1
    | FormFieldExpressionV1
    | EventEntityRefExpressionV1
    | EntityFieldExpressionV1,
    Field(discriminator="kind"),
]


class AllPredicateV1(StrictPrototypeModel):
    kind: Literal["all"]
    items: Annotated[list[RuntimePredicateV1], Field(min_length=1, max_length=20)]


class RoleIsPredicateV1(StrictPrototypeModel):
    kind: Literal["roleIs"]
    role_id: EntityId


class FormValidPredicateV1(StrictPrototypeModel):
    kind: Literal["formValid"]
    form_id: EntityId


class ComparePredicateV1(StrictPrototypeModel):
    kind: Literal["compare"]
    operator: Literal["eq", "ne"]
    left: RuntimeExpressionV1
    right: RuntimeExpressionV1


type RuntimePredicateV1 = Annotated[
    AllPredicateV1 | RoleIsPredicateV1 | FormValidPredicateV1 | ComparePredicateV1,
    Field(discriminator="kind"),
]


class SetVariableEffectV1(StrictPrototypeModel):
    kind: Literal["setVariable"]
    variable_id: EntityId
    value: RuntimeExpressionV1


class ValidateFormEffectV1(StrictPrototypeModel):
    kind: Literal["validateForm"]
    form_id: EntityId


class RuntimeFieldAssignmentV1(StrictPrototypeModel):
    field_id: EntityId
    value: RuntimeExpressionV1


class CreateEntityEffectV1(StrictPrototypeModel):
    kind: Literal["createEntity"]
    schema_id: EntityId
    result_variable_id: EntityId
    values: Annotated[list[RuntimeFieldAssignmentV1], Field(max_length=100)]


class UpdateEntityEffectV1(StrictPrototypeModel):
    kind: Literal["updateEntity"]
    schema_id: EntityId
    entity_ref: VariableExpressionV1 | EventEntityRefExpressionV1
    updates: Annotated[list[RuntimeFieldAssignmentV1], Field(min_length=1, max_length=100)]


class NavigateEffectV1(StrictPrototypeModel):
    kind: Literal["navigate"]
    target_page_id: EntityId


class NotifyEffectV1(StrictPrototypeModel):
    kind: Literal["notify"]
    level: Literal["info", "success", "warning", "error"]
    message: Annotated[str, Field(min_length=1, max_length=240)]


type RuntimeEffectV1 = Annotated[
    SetVariableEffectV1
    | ValidateFormEffectV1
    | CreateEntityEffectV1
    | UpdateEntityEffectV1
    | NavigateEffectV1
    | NotifyEffectV1,
    Field(discriminator="kind"),
]


class RuntimeTriggerV1(StrictPrototypeModel):
    kind: Literal["nodeEvent"]
    node_id: EntityId
    event: Literal["click", "submit", "rowActivated"]


class RuntimeRuleV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    enabled: bool
    trigger: RuntimeTriggerV1
    guard: RuntimePredicateV1 | None
    effects: Annotated[list[RuntimeEffectV1], Field(min_length=1, max_length=100)]
    guard_false_effects: Annotated[list[RuntimeEffectV1], Field(max_length=100)]


class TextViewBindingV1(StrictPrototypeModel):
    id: EntityId
    node_id: EntityId
    target: Literal["textContent"]
    value: RuntimeExpressionV1


class VisibilityViewBindingV1(StrictPrototypeModel):
    id: EntityId
    node_id: EntityId
    target: Literal["visibility"]
    predicate: RuntimePredicateV1


class TableRowsViewBindingV1(StrictPrototypeModel):
    id: EntityId
    node_id: EntityId
    target: Literal["tableRows"]
    schema_id: EntityId
    sort_field_id: EntityId | None
    sort_direction: Literal["asc", "desc"]


type RuntimeViewBindingV1 = Annotated[
    TextViewBindingV1 | VisibilityViewBindingV1 | TableRowsViewBindingV1,
    Field(discriminator="target"),
]


class RuntimeVariableValueV1(StrictPrototypeModel):
    variable_id: EntityId
    value: RuntimeValueV1


class RuntimeFieldValueV1(StrictPrototypeModel):
    field_id: EntityId
    value: RuntimeValueV1


class RuntimeEntityV1(StrictPrototypeModel):
    id: EntityId
    schema_id: EntityId
    fields: Annotated[list[RuntimeFieldValueV1], Field(max_length=100)]


class RuntimeEntitySetV1(StrictPrototypeModel):
    schema_id: EntityId
    entities: Annotated[list[RuntimeEntityV1], Field(max_length=200)]


class RuntimeScenarioV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    actor_role_id: EntityId
    start_page_id: EntityId
    initial_variables: Annotated[list[RuntimeVariableValueV1], Field(max_length=100)]
    entity_fixtures: Annotated[list[RuntimeEntitySetV1], Field(max_length=50)]
    allow_simulated_role_switch: bool


class RuntimeDefinitionV1(StrictPrototypeModel):
    runtime_schema_version: Literal[1]
    page_ids: Annotated[list[EntityId], Field(min_length=1, max_length=20)]
    roles: Annotated[list[RuntimeRoleV1], Field(min_length=1, max_length=20)]
    variables: Annotated[list[RuntimeVariableV1], Field(max_length=100)]
    entity_schemas: Annotated[list[RuntimeEntitySchemaV1], Field(max_length=50)]
    forms: Annotated[list[RuntimeFormV1], Field(max_length=50)]
    view_bindings: Annotated[list[RuntimeViewBindingV1], Field(max_length=200)]
    rules: Annotated[list[RuntimeRuleV1], Field(max_length=100)]
    scenarios: Annotated[list[RuntimeScenarioV1], Field(min_length=1, max_length=20)]


class PrototypeDocumentV1(StrictPrototypeModel):
    schema_version: Literal[1]
    id: EntityId
    title: Annotated[str, Field(min_length=1, max_length=120)]
    locale: Literal["zh-CN", "en-US"]
    settings: PrototypeSettingsV1
    tokens: DesignTokensV1
    component_definitions: Annotated[list[ComponentDefinitionV1], Field(max_length=50)]
    pages: Annotated[list[PrototypePageV1], Field(min_length=1, max_length=20)]
    navigation: NavigationDefinitionV1
    flows: Annotated[list[PrototypeFlowV1], Field(max_length=100)]
    runtime: RuntimeDefinitionV1
    asset_refs: Annotated[list[AssetRefV1], Field(max_length=200)]

    @model_validator(mode="after")
    def validate_document_graph(self) -> PrototypeDocumentV1:
        page_ids = _unique((page.id for page in self.pages), "page ID")
        _unique((page.key for page in self.pages), "page key")
        _unique((page.route for page in self.pages), "page route")
        node_ids: set[str] = set()
        for page in self.pages:
            _collect_node_ids(page.root, node_ids)
        for definition in self.component_definitions:
            _collect_node_ids(definition.root, node_ids)
        _unique((item.id for item in self.navigation.items), "navigation item ID")
        _unique((item.key for item in self.navigation.items), "navigation item key")
        for item in self.navigation.items:
            if item.target_page_id not in page_ids:
                raise ValueError(f"navigation item {item.id} references an unknown page")
        if set(self.runtime.page_ids) != page_ids or len(self.runtime.page_ids) != len(page_ids):
            raise ValueError("runtime page IDs must match document pages exactly")
        form_ids = _unique((form.id for form in self.runtime.forms), "runtime form ID")
        rule_ids = _unique((rule.id for rule in self.runtime.rules), "runtime rule ID")
        _validate_runtime_semantics(
            self.runtime,
            page_ids=page_ids,
            node_ids=node_ids,
        )
        for page in self.pages:
            _validate_node_references(page.root, form_ids)
        for definition in self.component_definitions:
            _validate_node_references(definition.root, form_ids)
        for flow in self.flows:
            if flow.rule_id not in rule_ids or flow.from_node_id not in node_ids:
                raise ValueError(f"flow {flow.id} references an unknown rule or node")
            if flow.to_page_id is not None and flow.to_page_id not in page_ids:
                raise ValueError(f"flow {flow.id} references an unknown target page")
        entity_ids = [self.id]
        entity_ids.extend(page_ids)
        entity_ids.extend(node_ids)
        entity_ids.extend(_table_row_ids(self))
        entity_ids.extend(definition.id for definition in self.component_definitions)
        entity_ids.extend(item.id for item in self.navigation.items)
        entity_ids.extend(flow.id for flow in self.flows)
        entity_ids.extend(asset.id for asset in self.asset_refs)
        entity_ids.extend(_runtime_entity_ids(self.runtime))
        _unique(entity_ids, "entity ID")
        return self


class NewPrototypeDocumentV1(StrictPrototypeModel):
    schema_version: Literal[1]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    locale: Literal["zh-CN", "en-US"]
    settings: PrototypeSettingsV1
    tokens: DesignTokensV1
    component_definitions: Annotated[list[ComponentDefinitionV1], Field(max_length=50)]
    pages: Annotated[list[PrototypePageV1], Field(min_length=1, max_length=20)]
    navigation: NavigationDefinitionV1
    flows: Annotated[list[PrototypeFlowV1], Field(max_length=100)]
    runtime: RuntimeDefinitionV1
    asset_refs: Annotated[list[AssetRefV1], Field(max_length=200)]

    def materialize(self, document_id: str) -> PrototypeDocumentV1:
        payload = self.model_dump(mode="json", by_alias=True)
        payload["id"] = document_id
        return PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def _unique(values: Iterable[str], label: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
    return seen


def _collect_node_ids(node: UINodeV1, seen: set[str]) -> None:
    if node.id in seen:
        raise ValueError(f"duplicate node ID: {node.id}")
    seen.add(node.id)
    if isinstance(node, (StackNodeV1, FormNodeV1)):
        for child in node.children:
            _collect_node_ids(child, seen)


def _validate_node_references(node: UINodeV1, form_ids: set[str]) -> None:
    if isinstance(node, FormNodeV1) and node.form_definition_id not in form_ids:
        raise ValueError(f"form node {node.id} references an unknown runtime form")
    if isinstance(node, (StackNodeV1, FormNodeV1)):
        for child in node.children:
            _validate_node_references(child, form_ids)


def _runtime_entity_ids(runtime: RuntimeDefinitionV1) -> list[str]:
    result: list[str] = []
    result.extend(role.id for role in runtime.roles)
    result.extend(variable.id for variable in runtime.variables)
    for schema in runtime.entity_schemas:
        result.append(schema.id)
        result.extend(field.id for field in schema.fields)
    for form in runtime.forms:
        result.append(form.id)
        result.extend(field.id for field in form.fields)
    result.extend(binding.id for binding in runtime.view_bindings)
    result.extend(rule.id for rule in runtime.rules)
    for scenario in runtime.scenarios:
        result.append(scenario.id)
        for entity_set in scenario.entity_fixtures:
            result.extend(entity.id for entity in entity_set.entities)
    return result


def _validate_runtime_semantics(
    runtime: RuntimeDefinitionV1,
    *,
    page_ids: set[str],
    node_ids: set[str],
) -> None:
    _unique((role.id for role in runtime.roles), "runtime role ID")
    _unique((variable.id for variable in runtime.variables), "runtime variable ID")
    _unique((schema.id for schema in runtime.entity_schemas), "runtime schema ID")
    _unique((form.id for form in runtime.forms), "runtime form ID")
    _unique((binding.id for binding in runtime.view_bindings), "runtime view-binding ID")
    _unique((rule.id for rule in runtime.rules), "runtime rule ID")
    _unique((scenario.id for scenario in runtime.scenarios), "runtime scenario ID")
    _unique(
        (field.id for schema in runtime.entity_schemas for field in schema.fields),
        "runtime entity field ID",
    )
    _unique(
        (field.id for form in runtime.forms for field in form.fields),
        "runtime form field ID",
    )
    _unique((role.key for role in runtime.roles), "runtime role key")
    _unique((variable.key for variable in runtime.variables), "runtime variable key")
    _unique((schema.key for schema in runtime.entity_schemas), "runtime schema key")
    _unique((form.key for form in runtime.forms), "runtime form key")
    _unique((rule.key for rule in runtime.rules), "runtime rule key")
    _unique((scenario.key for scenario in runtime.scenarios), "runtime scenario key")
    role_ids = {role.id for role in runtime.roles}
    variable_by_id = {variable.id: variable for variable in runtime.variables}
    schema_by_id = {schema.id: schema for schema in runtime.entity_schemas}
    form_by_id = {form.id: form for form in runtime.forms}
    entity_field_by_id: dict[str, RuntimeEntityFieldV1] = {}
    for schema in runtime.entity_schemas:
        _unique(
            (entity_field.key for entity_field in schema.fields),
            f"runtime schema {schema.id} field key",
        )
        for entity_field in schema.fields:
            entity_field_by_id[entity_field.id] = entity_field
    for form in runtime.forms:
        _unique(
            (form_field.key for form_field in form.fields),
            f"runtime form {form.id} field key",
        )
        for form_field in form.fields:
            if form_field.initial_value.type != form_field.value_type:
                raise ValueError(
                    f"runtime form field {form_field.id} initial value type is invalid"
                )
            if form_field.value_type == "string" and form_field.min_integer is not None:
                raise ValueError(f"runtime string field {form_field.id} cannot define minInteger")
    for variable in runtime.variables:
        if not _runtime_value_matches(
            variable.default_value,
            variable.value_type,
            variable.nullable,
        ):
            raise ValueError(f"runtime variable {variable.id} default value type is invalid")
        _validate_runtime_value(variable.default_value, schema_by_id)
    for binding in runtime.view_bindings:
        if binding.node_id not in node_ids:
            raise ValueError(f"runtime view binding {binding.id} references an unknown node")
        if isinstance(binding, TextViewBindingV1):
            _expression_type(
                binding.value,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=False,
            )
        elif isinstance(binding, VisibilityViewBindingV1):
            _validate_predicate(
                binding.predicate,
                role_ids=role_ids,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=False,
            )
        else:
            binding_schema = schema_by_id.get(binding.schema_id)
            if binding_schema is None:
                raise ValueError(f"runtime view binding {binding.id} references an unknown schema")
            if binding.sort_field_id is not None and not any(
                field.id == binding.sort_field_id for field in binding_schema.fields
            ):
                raise ValueError(
                    f"runtime view binding {binding.id} sort field is not in its schema"
                )
    for rule in runtime.rules:
        if rule.trigger.node_id not in node_ids:
            raise ValueError(f"runtime rule {rule.id} references an unknown node")
        if rule.guard is not None:
            _validate_predicate(
                rule.guard,
                role_ids=role_ids,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=rule.trigger.event == "rowActivated",
            )
        for effect in (*rule.effects, *rule.guard_false_effects):
            _validate_effect(
                effect,
                page_ids=page_ids,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=rule.trigger.event == "rowActivated",
            )
    for scenario in runtime.scenarios:
        if scenario.actor_role_id not in role_ids or scenario.start_page_id not in page_ids:
            raise ValueError(f"runtime scenario {scenario.id} has an invalid start identity")
        _unique(
            (entry.variable_id for entry in scenario.initial_variables),
            f"runtime scenario {scenario.id} variable ID",
        )
        for entry in scenario.initial_variables:
            scenario_variable = variable_by_id.get(entry.variable_id)
            if scenario_variable is None:
                raise ValueError(f"runtime scenario {scenario.id} references an unknown variable")
            if not _runtime_value_matches(
                entry.value,
                scenario_variable.value_type,
                scenario_variable.nullable,
            ):
                raise ValueError(
                    f"runtime scenario {scenario.id} variable {scenario_variable.id} has an invalid type"
                )
            _validate_runtime_value(entry.value, schema_by_id)
        _unique(
            (fixture.schema_id for fixture in scenario.entity_fixtures),
            f"runtime scenario {scenario.id} fixture schema ID",
        )
        for fixture in scenario.entity_fixtures:
            fixture_schema = schema_by_id.get(fixture.schema_id)
            if fixture_schema is None:
                raise ValueError(f"runtime scenario {scenario.id} references an unknown schema")
            _unique(
                (entity.id for entity in fixture.entities),
                f"runtime scenario {scenario.id} fixture entity ID",
            )
            expected_field_ids = {field.id for field in fixture_schema.fields}
            for entity in fixture.entities:
                if entity.schema_id != fixture.schema_id:
                    raise ValueError(f"runtime fixture entity {entity.id} schema is inconsistent")
                field_ids = _unique(
                    (field.field_id for field in entity.fields),
                    f"runtime fixture entity {entity.id} field ID",
                )
                if field_ids != expected_field_ids:
                    raise ValueError(f"runtime fixture entity {entity.id} fields are incomplete")
                for field_value in entity.fields:
                    definition = entity_field_by_id[field_value.field_id]
                    if not _runtime_value_matches(
                        field_value.value,
                        definition.value_type,
                        definition.nullable,
                    ):
                        raise ValueError(
                            f"runtime fixture entity {entity.id} field value type is invalid"
                        )
                    _validate_runtime_value(field_value.value, schema_by_id)


def _runtime_value_matches(
    value: RuntimeValueV1,
    expected_type: str,
    nullable: bool,
) -> bool:
    if value.type == "null":
        return nullable or expected_type == "null"
    return value.type == expected_type


def _validate_runtime_value(
    value: RuntimeValueV1,
    schema_by_id: dict[str, RuntimeEntitySchemaV1],
) -> None:
    if isinstance(value, EntityRefRuntimeValueV1) and value.schema_id not in schema_by_id:
        raise ValueError("runtime entity reference value uses an unknown schema")


def _expression_type(
    expression: RuntimeExpressionV1,
    *,
    variable_by_id: dict[str, RuntimeVariableV1],
    schema_by_id: dict[str, RuntimeEntitySchemaV1],
    form_by_id: dict[str, RuntimeFormV1],
    entity_field_by_id: dict[str, RuntimeEntityFieldV1],
    allow_event_entity_ref: bool,
) -> str:
    if isinstance(expression, LiteralExpressionV1):
        _validate_runtime_value(expression.value, schema_by_id)
        return expression.value.type
    if isinstance(expression, VariableExpressionV1):
        variable = variable_by_id.get(expression.variable_id)
        if variable is None:
            raise ValueError("runtime expression references an unknown variable")
        return variable.value_type
    if isinstance(expression, FormFieldExpressionV1):
        form = form_by_id.get(expression.form_id)
        if form is None:
            raise ValueError("runtime expression references an unknown form")
        field = next((item for item in form.fields if item.id == expression.field_id), None)
        if field is None:
            raise ValueError("runtime expression form field does not belong to its form")
        return field.value_type
    if isinstance(expression, EventEntityRefExpressionV1):
        if not allow_event_entity_ref:
            raise ValueError("runtime expression cannot reference an event entity in this context")
        return "entityRef"
    if isinstance(expression.entity_ref, VariableExpressionV1):
        ref_type = _expression_type(
            expression.entity_ref,
            variable_by_id=variable_by_id,
            schema_by_id=schema_by_id,
            form_by_id=form_by_id,
            entity_field_by_id=entity_field_by_id,
            allow_event_entity_ref=allow_event_entity_ref,
        )
        if ref_type != "entityRef":
            raise ValueError("runtime entity-field expression requires an entity reference")
    elif not allow_event_entity_ref:
        raise ValueError("runtime expression cannot reference an event entity in this context")
    field_definition = entity_field_by_id.get(expression.field_id)
    if field_definition is None:
        raise ValueError("runtime expression references an unknown entity field")
    if not _runtime_value_matches(expression.fallback, field_definition.value_type, True):
        raise ValueError("runtime entity-field fallback type is invalid")
    _validate_runtime_value(expression.fallback, schema_by_id)
    return field_definition.value_type


def _validate_predicate(
    predicate: RuntimePredicateV1,
    *,
    role_ids: set[str],
    variable_by_id: dict[str, RuntimeVariableV1],
    schema_by_id: dict[str, RuntimeEntitySchemaV1],
    form_by_id: dict[str, RuntimeFormV1],
    entity_field_by_id: dict[str, RuntimeEntityFieldV1],
    allow_event_entity_ref: bool,
) -> None:
    if isinstance(predicate, AllPredicateV1):
        for item in predicate.items:
            _validate_predicate(
                item,
                role_ids=role_ids,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=allow_event_entity_ref,
            )
        return
    if isinstance(predicate, RoleIsPredicateV1):
        if predicate.role_id not in role_ids:
            raise ValueError("runtime predicate references an unknown role")
        return
    if isinstance(predicate, FormValidPredicateV1):
        if predicate.form_id not in form_by_id:
            raise ValueError("runtime predicate references an unknown form")
        return
    left_type = _expression_type(
        predicate.left,
        variable_by_id=variable_by_id,
        schema_by_id=schema_by_id,
        form_by_id=form_by_id,
        entity_field_by_id=entity_field_by_id,
        allow_event_entity_ref=allow_event_entity_ref,
    )
    right_type = _expression_type(
        predicate.right,
        variable_by_id=variable_by_id,
        schema_by_id=schema_by_id,
        form_by_id=form_by_id,
        entity_field_by_id=entity_field_by_id,
        allow_event_entity_ref=allow_event_entity_ref,
    )
    if left_type != "null" and right_type != "null" and left_type != right_type:
        raise ValueError("runtime comparison expression types do not match")


def _validate_effect(
    effect: RuntimeEffectV1,
    *,
    page_ids: set[str],
    variable_by_id: dict[str, RuntimeVariableV1],
    schema_by_id: dict[str, RuntimeEntitySchemaV1],
    form_by_id: dict[str, RuntimeFormV1],
    entity_field_by_id: dict[str, RuntimeEntityFieldV1],
    allow_event_entity_ref: bool,
) -> None:
    if isinstance(effect, SetVariableEffectV1):
        variable = variable_by_id.get(effect.variable_id)
        if variable is None:
            raise ValueError("runtime effect references an unknown variable")
        if (
            _expression_type(
                effect.value,
                variable_by_id=variable_by_id,
                schema_by_id=schema_by_id,
                form_by_id=form_by_id,
                entity_field_by_id=entity_field_by_id,
                allow_event_entity_ref=allow_event_entity_ref,
            )
            != variable.value_type
        ):
            raise ValueError("runtime set-variable expression type is invalid")
        return
    if isinstance(effect, ValidateFormEffectV1):
        if effect.form_id not in form_by_id:
            raise ValueError("runtime effect references an unknown form")
        return
    if isinstance(effect, NavigateEffectV1):
        if effect.target_page_id not in page_ids:
            raise ValueError("runtime effect references an unknown page")
        return
    if isinstance(effect, NotifyEffectV1):
        return
    schema = schema_by_id.get(effect.schema_id)
    if schema is None:
        raise ValueError("runtime entity effect references an unknown schema")
    if isinstance(effect, CreateEntityEffectV1):
        result_variable = variable_by_id.get(effect.result_variable_id)
        if result_variable is None or result_variable.value_type != "entityRef":
            raise ValueError("runtime create-entity result variable is invalid")
        assignments = effect.values
    else:
        if isinstance(effect.entity_ref, VariableExpressionV1):
            variable = variable_by_id.get(effect.entity_ref.variable_id)
            if variable is None or variable.value_type != "entityRef":
                raise ValueError("runtime update-entity reference variable is invalid")
        elif not allow_event_entity_ref:
            raise ValueError("runtime update-entity effect cannot use an event entity here")
        assignments = effect.updates
    assignment_ids = _unique(
        (assignment.field_id for assignment in assignments),
        "runtime entity effect field ID",
    )
    schema_fields = {field.id: field for field in schema.fields}
    if not assignment_ids.issubset(schema_fields):
        raise ValueError("runtime entity effect field does not belong to its schema")
    for assignment in assignments:
        expression_type = _expression_type(
            assignment.value,
            variable_by_id=variable_by_id,
            schema_by_id=schema_by_id,
            form_by_id=form_by_id,
            entity_field_by_id=entity_field_by_id,
            allow_event_entity_ref=allow_event_entity_ref,
        )
        if expression_type != schema_fields[assignment.field_id].value_type:
            raise ValueError("runtime entity effect assignment type is invalid")


def _table_row_ids(document: PrototypeDocumentV1) -> list[str]:
    result: list[str] = []

    def collect(node: UINodeV1) -> None:
        if isinstance(node, TableNodeV1):
            result.extend(row.id for row in node.rows)
        if isinstance(node, (StackNodeV1, FormNodeV1)):
            for child in node.children:
                collect(child)

    for page in document.pages:
        collect(page.root)
    for definition in document.component_definitions:
        collect(definition.root)
    return result


class NewNodeCommonV1(StrictPrototypeModel):
    new_node_key: TechnicalKey
    name: Annotated[str, Field(min_length=1, max_length=80)]
    visibility: Literal["visible", "hidden"]
    layout_item: LayoutItemV1
    responsive: Annotated[list[ResponsiveOverrideV1], Field(max_length=3)]

    @model_validator(mode="after")
    def validate_responsive_overrides(self) -> NewNodeCommonV1:
        _unique((item.breakpoint for item in self.responsive), "responsive breakpoint")
        return self


class NewStackNodeV1(NewNodeCommonV1):
    type: Literal["Stack"]
    direction: Literal["row", "column"]
    gap: Annotated[int, Field(ge=0, le=128)]
    align: Literal["start", "center", "end", "stretch"]
    justify: Literal["start", "center", "end", "between"]
    padding: PaddingV1
    children: Annotated[list[NewUINodeV1], Field(max_length=500)]


class NewFormNodeV1(NewNodeCommonV1):
    type: Literal["Form"]
    form_definition_id: EntityId
    gap: Annotated[int, Field(ge=0, le=128)]
    padding: PaddingV1
    children: Annotated[list[NewUINodeV1], Field(min_length=1, max_length=200)]


class NewTextNodeV1(NewNodeCommonV1):
    type: Literal["Text"]
    content: Annotated[str, Field(max_length=8_000)]
    semantic: Literal["heading", "body", "label", "caption"]
    tone: Literal["default", "muted", "success", "warning", "danger"]


class NewInputNodeV1(NewNodeCommonV1):
    type: Literal["Input"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    placeholder: Annotated[str, Field(max_length=240)]
    value: Annotated[str, Field(max_length=8_000)]
    input_type: Literal["text", "number", "email"]
    required: bool
    disabled: bool


class NewButtonNodeV1(NewNodeCommonV1):
    type: Literal["Button"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    variant: Literal["primary", "secondary", "danger", "ghost"]
    size: Literal["small", "medium", "large"]
    disabled: bool
    icon_name: Annotated[str, Field(min_length=1, max_length=80)] | None


class NewTableNodeV1(NewNodeCommonV1):
    type: Literal["Table"]
    columns: Annotated[list[TableColumnV1], Field(min_length=1, max_length=30)]
    rows: Annotated[list[TableRowV1], Field(max_length=200)]
    density: Literal["compact", "comfortable"]

    @model_validator(mode="after")
    def validate_table_shape(self) -> NewTableNodeV1:
        column_keys = _unique((column.key for column in self.columns), "table column key")
        _unique((row.id for row in self.rows), "table row ID")
        for row in self.rows:
            cell_keys = _unique((cell.column_key for cell in row.cells), "table cell column key")
            if cell_keys != column_keys:
                raise ValueError(f"table row {row.id} cells must match the table columns")
        return self


type NewUINodeV1 = Annotated[
    NewStackNodeV1
    | NewFormNodeV1
    | NewTextNodeV1
    | NewInputNodeV1
    | NewButtonNodeV1
    | NewTableNodeV1,
    Field(discriminator="type"),
]


class ExistingNodeRefV1(StrictPrototypeModel):
    kind: Literal["existing"]
    node_id: EntityId


class NewNodeRefV1(StrictPrototypeModel):
    kind: Literal["new"]
    new_node_key: TechnicalKey


type NodeRefV1 = Annotated[ExistingNodeRefV1 | NewNodeRefV1, Field(discriminator="kind")]


class InsertNodeCommandV1(StrictPrototypeModel):
    kind: Literal["insertNode"]
    parent: NodeRefV1
    slot: None
    index: Annotated[int, Field(ge=0)]
    node: NewUINodeV1


class MoveNodeCommandV1(StrictPrototypeModel):
    kind: Literal["moveNode"]
    node: NodeRefV1
    target_parent: NodeRefV1
    target_slot: None
    target_index: Annotated[int, Field(ge=0)]


class RemoveNodeCommandV1(StrictPrototypeModel):
    kind: Literal["removeNode"]
    node_id: EntityId


class TextContentUpdateV1(StrictPrototypeModel):
    kind: Literal["textContent"]
    content: Annotated[str, Field(max_length=8_000)]


class LabelUpdateV1(StrictPrototypeModel):
    kind: Literal["label"]
    label: Annotated[str, Field(min_length=1, max_length=120)]


class PlaceholderUpdateV1(StrictPrototypeModel):
    kind: Literal["placeholder"]
    placeholder: Annotated[str, Field(max_length=240)]


class ButtonVariantUpdateV1(StrictPrototypeModel):
    kind: Literal["buttonVariant"]
    variant: Literal["primary", "secondary", "danger", "ghost"]


class DisabledUpdateV1(StrictPrototypeModel):
    kind: Literal["disabled"]
    disabled: bool


class InputValueUpdateV1(StrictPrototypeModel):
    kind: Literal["inputValue"]
    value: Annotated[str, Field(max_length=8_000)]


class TableDataUpdateV1(StrictPrototypeModel):
    kind: Literal["tableData"]
    columns: Annotated[list[TableColumnV1], Field(min_length=1, max_length=30)]
    rows: Annotated[list[TableRowV1], Field(max_length=200)]


class VisibilityUpdateV1(StrictPrototypeModel):
    kind: Literal["visibility"]
    visibility: Literal["visible", "hidden"]


type NodePropertyUpdateV1 = Annotated[
    TextContentUpdateV1
    | LabelUpdateV1
    | PlaceholderUpdateV1
    | ButtonVariantUpdateV1
    | DisabledUpdateV1
    | InputValueUpdateV1
    | TableDataUpdateV1
    | VisibilityUpdateV1,
    Field(discriminator="kind"),
]


class SetNodePropertyCommandV1(StrictPrototypeModel):
    kind: Literal["setNodeProperty"]
    node: NodeRefV1
    update: NodePropertyUpdateV1


class SetNodeLayoutCommandV1(StrictPrototypeModel):
    kind: Literal["setNodeLayout"]
    node: NodeRefV1
    update: LayoutItemUpdateV1


class ReorderPageCommandV1(StrictPrototypeModel):
    kind: Literal["reorderPage"]
    page_id: EntityId
    target_index: Annotated[int, Field(ge=0)]


type DomainCommandV1 = Annotated[
    InsertNodeCommandV1
    | MoveNodeCommandV1
    | RemoveNodeCommandV1
    | SetNodePropertyCommandV1
    | SetNodeLayoutCommandV1
    | ReorderPageCommandV1,
    Field(discriminator="kind"),
]


class DomainCommandBatchV1(StrictPrototypeModel):
    command_contract_version: Literal[1]
    commands: Annotated[list[DomainCommandV1], Field(min_length=1, max_length=100)]
    summary: Annotated[str, Field(min_length=1, max_length=240)]


class RestoreNodeCommandV1(StrictPrototypeModel):
    kind: Literal["restoreNode"]
    parent_id: EntityId
    index: Annotated[int, Field(ge=0)]
    node: UINodeV1


type InverseCommandV1 = Annotated[
    MoveNodeCommandV1
    | RemoveNodeCommandV1
    | SetNodePropertyCommandV1
    | SetNodeLayoutCommandV1
    | ReorderPageCommandV1
    | RestoreNodeCommandV1,
    Field(discriminator="kind"),
]


class InverseCommandBatchV1(StrictPrototypeModel):
    command_contract_version: Literal[1]
    commands: Annotated[list[InverseCommandV1], Field(min_length=1, max_length=100)]


@dataclass(frozen=True, slots=True)
class CommandExecutionResultV1:
    document: PrototypeDocumentV1
    inverse_commands: InverseCommandBatchV1
    allocated_entity_ids: tuple[tuple[str, str], ...]
    affected_entity_ids: tuple[str, ...]
    base_document_hash: str
    result_document_hash: str


def document_payload(document: PrototypeDocumentV1) -> dict[str, object]:
    return document.model_dump(mode="json", by_alias=True)


def document_hash(document: PrototypeDocumentV1) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(canonical_json_bytes(document_payload(document))).hexdigest()}"


def canonical_model_json(model: StrictPrototypeModel) -> str:
    return canonical_json_bytes(model.model_dump(mode="json", by_alias=True)).decode("utf-8")


def parse_prototype_document_json(payload: bytes | str) -> PrototypeDocumentV1:
    try:
        return PrototypeDocumentV1.model_validate_json(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "document_invalid", "prototype document does not satisfy schema version 1"
        ) from exc


def parse_command_batch_json(payload: str) -> DomainCommandBatchV1:
    try:
        return DomainCommandBatchV1.model_validate_json(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "command_batch_invalid", "prototype command batch does not satisfy contract version 1"
        ) from exc


def parse_inverse_command_batch_json(payload: str) -> InverseCommandBatchV1:
    try:
        return InverseCommandBatchV1.model_validate_json(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "inverse_command_batch_invalid",
            "prototype inverse command batch does not satisfy contract version 1",
        ) from exc


def command_batch_hash(batch: DomainCommandBatchV1) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(canonical_json_bytes(batch.model_dump(mode='json', by_alias=True))).hexdigest()}"


def execute_command_batch(
    document: PrototypeDocumentV1,
    batch: DomainCommandBatchV1,
    *,
    draft_id: str,
    client_request_id: str,
) -> CommandExecutionResultV1:
    base_hash = document_hash(document)
    current = document
    allocated: dict[str, str] = {}
    inverse: list[InverseCommandV1] = []
    affected: set[str] = set()
    for command in batch.commands:
        current, command_inverse, command_affected = _execute_command(
            current,
            command,
            draft_id=draft_id,
            client_request_id=client_request_id,
            allocated=allocated,
        )
        inverse.insert(0, command_inverse)
        affected.update(command_affected)
    serialized_inverse = InverseCommandBatchV1(
        command_contract_version=COMMAND_CONTRACT_VERSION,
        commands=inverse,
    )
    if (
        len(canonical_model_json(batch).encode("utf-8"))
        + len(canonical_model_json(serialized_inverse).encode("utf-8"))
        > 262_144
    ):
        raise StructuredPrototypeContractError(
            "command_batch_too_large",
            "prototype command and inverse payloads exceed 256 KiB",
        )
    return CommandExecutionResultV1(
        document=current,
        inverse_commands=serialized_inverse,
        allocated_entity_ids=tuple(sorted(allocated.items())),
        affected_entity_ids=tuple(sorted(affected)),
        base_document_hash=base_hash,
        result_document_hash=document_hash(current),
    )


def apply_inverse_commands(
    document: PrototypeDocumentV1,
    batch: InverseCommandBatchV1,
) -> PrototypeDocumentV1:
    current = document
    for command in batch.commands:
        current = _apply_inverse_command(current, command)
    return current


def _execute_command(
    document: PrototypeDocumentV1,
    command: DomainCommandV1,
    *,
    draft_id: str,
    client_request_id: str,
    allocated: dict[str, str],
) -> tuple[PrototypeDocumentV1, InverseCommandV1, set[str]]:
    if isinstance(command, InsertNodeCommandV1):
        parent_id = _resolve_node_ref(command.parent, allocated)
        node = _allocate_new_node(
            command.node,
            draft_id=draft_id,
            client_request_id=client_request_id,
            allocated=allocated,
        )
        updated = _insert_node(document, parent_id, command.index, node)
        return (
            updated,
            RemoveNodeCommandV1(kind="removeNode", node_id=node.id),
            _node_id_set(node) | {parent_id},
        )
    if isinstance(command, MoveNodeCommandV1):
        node_id = _resolve_node_ref(command.node, allocated)
        target_parent_id = _resolve_node_ref(command.target_parent, allocated)
        node, source_parent_id, source_index = _locate_movable_node(document, node_id)
        if target_parent_id in _node_id_set(node):
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype node cannot move into its own subtree"
            )
        without_node = _remove_node(document, node_id)[0]
        updated = _insert_node(without_node, target_parent_id, command.target_index, node)
        inverse_move = MoveNodeCommandV1(
            kind="moveNode",
            node=ExistingNodeRefV1(kind="existing", node_id=node_id),
            target_parent=ExistingNodeRefV1(kind="existing", node_id=source_parent_id),
            target_slot=None,
            target_index=source_index,
        )
        return updated, inverse_move, {node_id, source_parent_id, target_parent_id}
    if isinstance(command, RemoveNodeCommandV1):
        updated, removed, parent_id, index = _remove_node(document, command.node_id)
        return (
            updated,
            RestoreNodeCommandV1(
                kind="restoreNode", parent_id=parent_id, index=index, node=removed
            ),
            _node_id_set(removed) | {parent_id},
        )
    if isinstance(command, SetNodePropertyCommandV1):
        node_id = _resolve_node_ref(command.node, allocated)
        node = _require_node(document, node_id)
        updated_node, old_update = _apply_property_update(node, command.update)
        updated = _replace_node(document, updated_node)
        return (
            updated,
            SetNodePropertyCommandV1(
                kind="setNodeProperty",
                node=ExistingNodeRefV1(kind="existing", node_id=node_id),
                update=old_update,
            ),
            {node_id},
        )
    if isinstance(command, SetNodeLayoutCommandV1):
        node_id = _resolve_node_ref(command.node, allocated)
        node = _require_node(document, node_id)
        updated_layout, old_layout = _apply_layout_update(node.layout_item, command.update)
        updated = _replace_node(document, node.model_copy(update={"layout_item": updated_layout}))
        return (
            updated,
            SetNodeLayoutCommandV1(
                kind="setNodeLayout",
                node=ExistingNodeRefV1(kind="existing", node_id=node_id),
                update=old_layout,
            ),
            {node_id},
        )
    if isinstance(command, ReorderPageCommandV1):
        pages = list(document.pages)
        page_source_index = next(
            (index for index, page in enumerate(pages) if page.id == command.page_id), None
        )
        if page_source_index is None:
            raise StructuredPrototypeContractError(
                "command_target_missing", "prototype page does not exist"
            )
        page = pages.pop(page_source_index)
        if command.target_index > len(pages):
            raise StructuredPrototypeContractError(
                "command_index_invalid", "prototype page target index is out of range"
            )
        pages.insert(command.target_index, page)
        updated = document.model_copy(update={"pages": pages})
        return (
            updated,
            ReorderPageCommandV1(
                kind="reorderPage",
                page_id=command.page_id,
                target_index=page_source_index,
            ),
            {command.page_id},
        )
    raise AssertionError("unreachable domain command variant")


def _apply_inverse_command(
    document: PrototypeDocumentV1,
    command: InverseCommandV1,
) -> PrototypeDocumentV1:
    if isinstance(command, RestoreNodeCommandV1):
        return _insert_node(document, command.parent_id, command.index, command.node)
    if isinstance(command, RemoveNodeCommandV1):
        return _remove_node(document, command.node_id)[0]
    if isinstance(command, MoveNodeCommandV1):
        node_id = _existing_ref_id(command.node)
        parent_id = _existing_ref_id(command.target_parent)
        node = _require_node(document, node_id)
        without_node = _remove_node(document, node_id)[0]
        return _insert_node(without_node, parent_id, command.target_index, node)
    if isinstance(command, SetNodePropertyCommandV1):
        node_id = _existing_ref_id(command.node)
        node, _ = _apply_property_update(_require_node(document, node_id), command.update)
        return _replace_node(document, node)
    if isinstance(command, SetNodeLayoutCommandV1):
        node_id = _existing_ref_id(command.node)
        node = _require_node(document, node_id)
        layout, _ = _apply_layout_update(node.layout_item, command.update)
        return _replace_node(document, node.model_copy(update={"layout_item": layout}))
    if isinstance(command, ReorderPageCommandV1):
        pages = list(document.pages)
        source_index = next(
            (index for index, page in enumerate(pages) if page.id == command.page_id), None
        )
        if source_index is None:
            raise StructuredPrototypeContractError(
                "command_target_missing", "prototype page does not exist"
            )
        page = pages.pop(source_index)
        pages.insert(command.target_index, page)
        return document.model_copy(update={"pages": pages})
    raise AssertionError("unreachable inverse command variant")


def _resolve_node_ref(reference: NodeRefV1, allocated: dict[str, str]) -> str:
    if isinstance(reference, ExistingNodeRefV1):
        return reference.node_id
    node_id = allocated.get(reference.new_node_key)
    if node_id is None:
        raise StructuredPrototypeContractError(
            "command_target_missing", "prototype new-node reference has not been allocated"
        )
    return node_id


def _existing_ref_id(reference: NodeRefV1) -> str:
    if not isinstance(reference, ExistingNodeRefV1):
        raise StructuredPrototypeContractError(
            "inverse_command_invalid", "persisted inverse must use existing node references"
        )
    return reference.node_id


def _allocate_new_node(
    node: NewUINodeV1,
    *,
    draft_id: str,
    client_request_id: str,
    allocated: dict[str, str],
) -> UINodeV1:
    if node.new_node_key in allocated:
        raise StructuredPrototypeContractError(
            "command_new_key_duplicate", "prototype new-node key is duplicated in the batch"
        )
    node_id = str(
        uuid5(
            PROTOTYPE_ENTITY_NAMESPACE,
            f"{draft_id}:{client_request_id}:node:{node.new_node_key}",
        )
    )
    allocated[node.new_node_key] = node_id
    payload = node.model_dump(mode="python", by_alias=True)
    payload.pop("newNodeKey")
    if isinstance(node, (NewStackNodeV1, NewFormNodeV1)):
        payload["children"] = [
            _allocate_new_node(
                child,
                draft_id=draft_id,
                client_request_id=client_request_id,
                allocated=allocated,
            )
            for child in node.children
        ]
    payload["id"] = node_id
    if isinstance(node, NewStackNodeV1):
        return StackNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewFormNodeV1):
        return FormNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewTextNodeV1):
        return TextNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewInputNodeV1):
        return InputNodeV1.model_validate(payload, strict=True)
    if isinstance(node, NewButtonNodeV1):
        return ButtonNodeV1.model_validate(payload, strict=True)
    return TableNodeV1.model_validate(payload, strict=True)


def _node_id_set(node: UINodeV1) -> set[str]:
    result = {node.id}
    if isinstance(node, (StackNodeV1, FormNodeV1)):
        for child in node.children:
            result.update(_node_id_set(child))
    return result


def _node_children(node: UINodeV1) -> list[UINodeV1] | None:
    if isinstance(node, (StackNodeV1, FormNodeV1)):
        return list(node.children)
    return None


def _replace_children(node: UINodeV1, children: list[UINodeV1]) -> UINodeV1:
    if not isinstance(node, (StackNodeV1, FormNodeV1)):
        raise StructuredPrototypeContractError(
            "command_target_invalid", "prototype target node is not a container"
        )
    return node.model_copy(update={"children": children})


def _walk_replace(node: UINodeV1, replacement: UINodeV1) -> tuple[UINodeV1, bool]:
    if node.id == replacement.id:
        return replacement, True
    children = _node_children(node)
    if children is None:
        return node, False
    for index, child in enumerate(children):
        updated_child, changed = _walk_replace(child, replacement)
        if changed:
            children[index] = updated_child
            return _replace_children(node, children), True
    return node, False


def _replace_node(document: PrototypeDocumentV1, replacement: UINodeV1) -> PrototypeDocumentV1:
    pages = list(document.pages)
    for index, page in enumerate(pages):
        root, changed = _walk_replace(page.root, replacement)
        if changed:
            pages[index] = page.model_copy(update={"root": root})
            return PrototypeDocumentV1.model_validate(
                document.model_copy(update={"pages": pages}).model_dump(mode="json", by_alias=True),
                strict=True,
            )
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype node does not exist"
    )


def _find_node(node: UINodeV1, node_id: str) -> UINodeV1 | None:
    if node.id == node_id:
        return node
    children = _node_children(node)
    if children is None:
        return None
    for child in children:
        found = _find_node(child, node_id)
        if found is not None:
            return found
    return None


def _require_node(document: PrototypeDocumentV1, node_id: str) -> UINodeV1:
    for page in document.pages:
        node = _find_node(page.root, node_id)
        if node is not None:
            return node
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype node does not exist"
    )


def _insert_into_tree(
    node: UINodeV1,
    parent_id: str,
    index: int,
    inserted: UINodeV1,
) -> tuple[UINodeV1, bool]:
    if node.id == parent_id:
        children = _node_children(node)
        if children is None:
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype target node is not a container"
            )
        if index > len(children):
            raise StructuredPrototypeContractError(
                "command_index_invalid", "prototype node target index is out of range"
            )
        children.insert(index, inserted)
        return _replace_children(node, children), True
    children = _node_children(node)
    if children is None:
        return node, False
    for child_index, child in enumerate(children):
        updated_child, changed = _insert_into_tree(child, parent_id, index, inserted)
        if changed:
            children[child_index] = updated_child
            return _replace_children(node, children), True
    return node, False


def _insert_node(
    document: PrototypeDocumentV1,
    parent_id: str,
    index: int,
    inserted: UINodeV1,
) -> PrototypeDocumentV1:
    if _node_id_set(inserted) & _document_node_ids(document):
        raise StructuredPrototypeContractError(
            "command_entity_id_conflict", "prototype inserted node ID already exists"
        )
    pages = list(document.pages)
    for page_index, page in enumerate(pages):
        root, changed = _insert_into_tree(page.root, parent_id, index, inserted)
        if changed:
            pages[page_index] = page.model_copy(update={"root": root})
            return PrototypeDocumentV1.model_validate(
                document.model_copy(update={"pages": pages}).model_dump(mode="json", by_alias=True),
                strict=True,
            )
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype parent node does not exist"
    )


def _document_node_ids(document: PrototypeDocumentV1) -> set[str]:
    result: set[str] = set()
    for page in document.pages:
        result.update(_node_id_set(page.root))
    for definition in document.component_definitions:
        result.update(_node_id_set(definition.root))
    return result


def _remove_from_tree(
    node: UINodeV1,
    node_id: str,
) -> tuple[UINodeV1, UINodeV1 | None, str | None, int | None]:
    children = _node_children(node)
    if children is None:
        return node, None, None, None
    for index, child in enumerate(children):
        if child.id == node_id:
            removed = children.pop(index)
            return _replace_children(node, children), removed, node.id, index
        updated_child, recursive_removed, parent_id, removed_index = _remove_from_tree(
            child, node_id
        )
        if recursive_removed is not None:
            children[index] = updated_child
            return (
                _replace_children(node, children),
                recursive_removed,
                parent_id,
                removed_index,
            )
    return node, None, None, None


def _remove_node(
    document: PrototypeDocumentV1,
    node_id: str,
) -> tuple[PrototypeDocumentV1, UINodeV1, str, int]:
    pages = list(document.pages)
    for page_index, page in enumerate(pages):
        if page.root.id == node_id:
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype page root cannot be removed"
            )
        root, removed, parent_id, removed_index = _remove_from_tree(page.root, node_id)
        if removed is not None and parent_id is not None and removed_index is not None:
            pages[page_index] = page.model_copy(update={"root": root})
            updated = PrototypeDocumentV1.model_validate(
                document.model_copy(update={"pages": pages}).model_dump(mode="json", by_alias=True),
                strict=True,
            )
            return updated, removed, parent_id, removed_index
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype node does not exist"
    )


def _locate_movable_node(
    document: PrototypeDocumentV1,
    node_id: str,
) -> tuple[UINodeV1, str, int]:
    for page in document.pages:
        if page.root.id == node_id:
            raise StructuredPrototypeContractError(
                "command_target_invalid", "prototype page root cannot be moved"
            )
        found = _locate_child(page.root, node_id)
        if found is not None:
            return found
    raise StructuredPrototypeContractError(
        "command_target_missing", "prototype node does not exist"
    )


def _locate_child(node: UINodeV1, node_id: str) -> tuple[UINodeV1, str, int] | None:
    children = _node_children(node)
    if children is None:
        return None
    for index, child in enumerate(children):
        if child.id == node_id:
            return child, node.id, index
        found = _locate_child(child, node_id)
        if found is not None:
            return found
    return None


def _apply_property_update(
    node: UINodeV1,
    update: NodePropertyUpdateV1,
) -> tuple[UINodeV1, NodePropertyUpdateV1]:
    if isinstance(update, VisibilityUpdateV1):
        return (
            node.model_copy(update={"visibility": update.visibility}),
            VisibilityUpdateV1(kind="visibility", visibility=node.visibility),
        )
    if isinstance(update, TextContentUpdateV1) and isinstance(node, TextNodeV1):
        return (
            node.model_copy(update={"content": update.content}),
            TextContentUpdateV1(kind="textContent", content=node.content),
        )
    if isinstance(update, LabelUpdateV1) and isinstance(node, (InputNodeV1, ButtonNodeV1)):
        return (
            node.model_copy(update={"label": update.label}),
            LabelUpdateV1(kind="label", label=node.label),
        )
    if isinstance(update, PlaceholderUpdateV1) and isinstance(node, InputNodeV1):
        return (
            node.model_copy(update={"placeholder": update.placeholder}),
            PlaceholderUpdateV1(kind="placeholder", placeholder=node.placeholder),
        )
    if isinstance(update, ButtonVariantUpdateV1) and isinstance(node, ButtonNodeV1):
        return (
            node.model_copy(update={"variant": update.variant}),
            ButtonVariantUpdateV1(kind="buttonVariant", variant=node.variant),
        )
    if isinstance(update, DisabledUpdateV1) and isinstance(node, (InputNodeV1, ButtonNodeV1)):
        return (
            node.model_copy(update={"disabled": update.disabled}),
            DisabledUpdateV1(kind="disabled", disabled=node.disabled),
        )
    if isinstance(update, InputValueUpdateV1) and isinstance(node, InputNodeV1):
        return (
            node.model_copy(update={"value": update.value}),
            InputValueUpdateV1(kind="inputValue", value=node.value),
        )
    if isinstance(update, TableDataUpdateV1) and isinstance(node, TableNodeV1):
        return (
            node.model_copy(update={"columns": update.columns, "rows": update.rows}),
            TableDataUpdateV1(kind="tableData", columns=node.columns, rows=node.rows),
        )
    raise StructuredPrototypeContractError(
        "command_property_invalid", "prototype property update is invalid for the node type"
    )


def _apply_layout_update(
    layout: LayoutItemV1,
    update: LayoutItemUpdateV1,
) -> tuple[LayoutItemV1, LayoutItemUpdateV1]:
    changed = update.model_dump(exclude_unset=True)
    previous = {field: getattr(layout, field) for field in changed}
    previous_aliases = {_camel_alias(field): value for field, value in previous.items()}
    return layout.model_copy(update=changed), LayoutItemUpdateV1.model_validate(
        previous_aliases, strict=True
    )
