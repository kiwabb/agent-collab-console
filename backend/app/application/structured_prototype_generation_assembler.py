from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid5

from pydantic import ValidationError

from app.application.structured_prototype_contracts import PrototypeDocumentV1
from app.application.structured_prototype_generation_contracts import (
    GeneratedButtonNodeV1,
    GeneratedFormNodeV1,
    GeneratedInputNodeV1,
    GeneratedNodeV1,
    GeneratedPageV1,
    GeneratedStackNodeV1,
    GeneratedTableNodeV1,
    GeneratedTextNodeV1,
    GenerationBlueprintV1,
    GenerationFoundationV1,
)

PROCUREMENT_ASSEMBLER_VERSION = "structured-prototype-procurement-assembler/v1"
PROCUREMENT_ENTITY_NAMESPACE = UUID("add80290-85a3-50b4-97e3-ab2560b83177")
PROCUREMENT_PAGE_KEYS = ("purchase-list", "purchase-create", "purchase-detail")
PROCUREMENT_PAGE_ROUTES = (
    ("purchase-list", "/purchases"),
    ("purchase-create", "/purchases/new"),
    ("purchase-detail", "/purchases/detail"),
)
PROCUREMENT_FLOW_INTENTS = (
    ("submit-request", "purchase-create", "submit-request", "submit", "purchase-detail"),
    ("select-request", "purchase-list", "request-table", "rowActivated", "purchase-detail"),
    ("approve-request", "purchase-detail", "approve-request", "click", "purchase-detail"),
)
PROCUREMENT_ROLE_INTENTS = ("applicant", "manager")
PROCUREMENT_ENTITY_INTENTS = ("purchase-request",)
PROCUREMENT_FORM_INTENTS = ("create-purchase-request",)
PROCUREMENT_SCENARIO_INTENTS = ("purchase-approval-happy-path",)
PROCUREMENT_START_PAGE_KEYS = ("purchase-create",)
PROCUREMENT_REQUIRED_COLOR_TOKEN_KEYS = ("primary", "surface")
PROCUREMENT_REQUIRED_SPACING_TOKEN_KEYS = ("panel-gap",)
PROCUREMENT_REQUEST_TABLE_COLUMN_KEYS = ("title", "amount", "status")
PROCUREMENT_ROOT_LOCAL_KEYS = {
    "purchase-list": "list-root",
    "purchase-create": "create-root",
    "purchase-detail": "detail-root",
}

_PAGE_SEEDS = {
    "purchase-list": "page-list",
    "purchase-create": "page-create",
    "purchase-detail": "page-detail",
}
_ROOT_SEEDS = {
    "purchase-list": "root-list",
    "purchase-create": "root-create",
    "purchase-detail": "root-detail",
}
PROCUREMENT_REQUIRED_NODE_TYPES: dict[str, dict[str, str]] = {
    "purchase-list": {"list-title": "Text", "request-table": "Table"},
    "purchase-create": {
        "create-form": "Form",
        "title-input": "Input",
        "amount-input": "Input",
        "submit-request": "Button",
    },
    "purchase-detail": {
        "detail-heading": "Text",
        "detail-title": "Text",
        "detail-status": "Text",
        "approve-request": "Button",
    },
}
_NODE_SEEDS = {
    ("purchase-list", "list-title"): "title-list",
    ("purchase-list", "request-table"): "table-list",
    ("purchase-create", "create-form"): "form-node-create",
    ("purchase-create", "title-input"): "input-title",
    ("purchase-create", "amount-input"): "input-amount",
    ("purchase-create", "submit-request"): "button-submit",
    ("purchase-detail", "detail-heading"): "title-detail",
    ("purchase-detail", "detail-title"): "detail-title",
    ("purchase-detail", "detail-status"): "detail-status",
    ("purchase-detail", "approve-request"): "button-approve",
}


class StructuredPrototypeGenerationAssemblyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def procurement_page_skeleton(
    page_key: str,
    title: str,
    route: str,
) -> dict[str, object]:
    root_common = {
        "name": title,
        "type": "Stack",
        "direction": "column",
        "gap": 16,
        "padding": 24,
    }
    if page_key == "purchase-list":
        children: list[dict[str, object]] = [
            {
                "localKey": "list-title",
                "name": "采购申请标题",
                "type": "Text",
                "content": "采购申请",
                "semantic": "heading",
                "tone": "default",
            },
            {
                "localKey": "request-table",
                "name": "采购申请表格",
                "type": "Table",
                "columns": [
                    {"key": "title", "label": "申请事项"},
                    {"key": "amount", "label": "金额"},
                    {"key": "status", "label": "状态"},
                ],
                "density": "comfortable",
            },
        ]
    elif page_key == "purchase-create":
        children = [
            {
                "localKey": "create-form",
                "name": "创建采购申请",
                "type": "Form",
                "formKey": "create-purchase-request",
                "gap": 16,
                "children": [
                    {
                        "localKey": "title-input",
                        "name": "申请事项",
                        "type": "Input",
                        "label": "申请事项",
                        "placeholder": "请输入申请事项",
                        "inputType": "text",
                        "required": True,
                    },
                    {
                        "localKey": "amount-input",
                        "name": "采购金额",
                        "type": "Input",
                        "label": "采购金额",
                        "placeholder": "请输入整数金额",
                        "inputType": "number",
                        "required": True,
                    },
                    {
                        "localKey": "submit-request",
                        "name": "提交申请",
                        "type": "Button",
                        "label": "提交申请",
                        "variant": "primary",
                    },
                ],
            }
        ]
    elif page_key == "purchase-detail":
        children = [
            {
                "localKey": "detail-heading",
                "name": "详情标题",
                "type": "Text",
                "content": "采购申请详情",
                "semantic": "heading",
                "tone": "default",
            },
            {
                "localKey": "detail-title",
                "name": "申请事项",
                "type": "Text",
                "content": "尚未选择申请",
                "semantic": "body",
                "tone": "default",
            },
            {
                "localKey": "detail-status",
                "name": "申请状态",
                "type": "Text",
                "content": "not-selected",
                "semantic": "label",
                "tone": "muted",
            },
            {
                "localKey": "approve-request",
                "name": "审批通过",
                "type": "Button",
                "label": "审批通过",
                "variant": "primary",
            },
        ]
    else:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            "page skeleton requires a procurement MVP page key",
        )
    return {
        "contractVersion": 1,
        "pageKey": page_key,
        "title": title,
        "route": route,
        "root": {
            "localKey": PROCUREMENT_ROOT_LOCAL_KEYS[page_key],
            **root_common,
            "children": children,
        },
    }


def _id(seed: str) -> str:
    return str(uuid5(PROCUREMENT_ENTITY_NAMESPACE, seed))


def _require_exact(values: Iterable[str], expected: set[str], label: str) -> None:
    actual = list(values)
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            f"{label} must match the procurement MVP contract exactly",
        )


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


def _common(node_id: str, node: GeneratedNodeV1) -> dict[str, object]:
    return {
        "id": node_id,
        "name": node.name,
        "visibility": node.visibility,
        "layoutItem": _layout(),
        "responsive": [],
    }


def _node_id(page_key: str, local_key: str) -> str:
    seed = _NODE_SEEDS.get((page_key, local_key), f"generated-{page_key}-{local_key}")
    return _id(seed)


def _convert_node(page_key: str, node: GeneratedNodeV1) -> dict[str, object]:
    common = _common(_node_id(page_key, node.local_key), node)
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
            "children": [_convert_node(page_key, child) for child in node.children],
        }
    if isinstance(node, GeneratedFormNodeV1):
        if node.form_key != "create-purchase-request":
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                "generated Form must reference create-purchase-request",
            )
        return {
            **common,
            "type": "Form",
            "formDefinitionId": _id("form-create"),
            "gap": node.gap,
            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "children": [_convert_node(page_key, child) for child in node.children],
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
        return {
            **common,
            "type": "Input",
            "label": node.label,
            "placeholder": node.placeholder,
            "value": "",
            "inputType": node.input_type,
            "required": node.required,
            "disabled": node.disabled,
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
        return {
            **common,
            "type": "Table",
            "columns": [column.model_dump(mode="json", by_alias=True) for column in node.columns],
            "rows": [],
            "density": node.density,
        }
    raise AssertionError("generation node union is exhaustive")


def _walk_nodes(node: GeneratedNodeV1) -> Iterable[GeneratedNodeV1]:
    yield node
    if isinstance(node, (GeneratedStackNodeV1, GeneratedFormNodeV1)):
        for child in node.children:
            yield from _walk_nodes(child)


def _validate_blueprint(blueprint: GenerationBlueprintV1) -> None:
    page_keys = tuple(page.page_key for page in blueprint.pages)
    if page_keys != PROCUREMENT_PAGE_KEYS:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            "blueprint pages must use the ordered three-page procurement MVP",
        )
    expected_routes = dict(PROCUREMENT_PAGE_ROUTES)
    if any(page.route != expected_routes[page.page_key] for page in blueprint.pages):
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid", "blueprint page routes do not match the procurement MVP"
        )
    _require_exact(
        (item.target_page_key for item in blueprint.navigation),
        set(PROCUREMENT_PAGE_KEYS),
        "navigation targets",
    )
    _require_exact(
        (flow.key for flow in blueprint.flow_intents),
        {intent[0] for intent in PROCUREMENT_FLOW_INTENTS},
        "flow intent keys",
    )
    flow_contract = {intent[0]: intent[1:] for intent in PROCUREMENT_FLOW_INTENTS}
    if any(
        (
            flow.source_page_key,
            flow.source_node_key,
            flow.event,
            flow.target_page_key,
        )
        != flow_contract[flow.key]
        for flow in blueprint.flow_intents
    ):
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid", "flow intents do not match the procurement MVP"
        )
    _require_exact(blueprint.role_intents, set(PROCUREMENT_ROLE_INTENTS), "role intents")
    _require_exact(blueprint.entity_intents, set(PROCUREMENT_ENTITY_INTENTS), "entity intents")
    _require_exact(blueprint.form_intents, set(PROCUREMENT_FORM_INTENTS), "form intents")
    _require_exact(
        blueprint.scenario_intents,
        set(PROCUREMENT_SCENARIO_INTENTS),
        "scenario intents",
    )
    _require_exact(blueprint.start_page_keys, set(PROCUREMENT_START_PAGE_KEYS), "start page keys")


def _validate_foundation(foundation: GenerationFoundationV1) -> None:
    color_keys = {token.key for token in foundation.colors}
    spacing_keys = {token.key for token in foundation.spacing}
    if not set(PROCUREMENT_REQUIRED_COLOR_TOKEN_KEYS).issubset(color_keys) or not set(
        PROCUREMENT_REQUIRED_SPACING_TOKEN_KEYS
    ).issubset(spacing_keys):
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            "foundation must define primary, surface, and panel-gap tokens",
        )


def validate_procurement_blueprint(blueprint: GenerationBlueprintV1) -> None:
    _validate_blueprint(blueprint)


def validate_procurement_foundation(foundation: GenerationFoundationV1) -> None:
    _validate_foundation(foundation)


def _validate_pages(
    blueprint: GenerationBlueprintV1,
    pages: tuple[GeneratedPageV1, ...],
) -> dict[str, GeneratedPageV1]:
    if tuple(page.page_key for page in pages) != PROCUREMENT_PAGE_KEYS:
        raise StructuredPrototypeGenerationAssemblyError(
            "generation_semantic_invalid",
            "page artifacts must be supplied in confirmed blueprint order",
        )
    blueprint_by_key = {page.page_key: page for page in blueprint.pages}
    result: dict[str, GeneratedPageV1] = {}
    for page in pages:
        confirmed = blueprint_by_key[page.page_key]
        if page.title != confirmed.title or page.route != confirmed.route:
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                f"generated page {page.page_key} does not match its confirmed blueprint",
            )
        nodes = {node.local_key: node for node in _walk_nodes(page.root)}
        expected_nodes = {
            PROCUREMENT_ROOT_LOCAL_KEYS[page.page_key]: "Stack",
            **PROCUREMENT_REQUIRED_NODE_TYPES[page.page_key],
        }
        if set(nodes) != set(expected_nodes):
            raise StructuredPrototypeGenerationAssemblyError(
                "generation_semantic_invalid",
                f"generated page {page.page_key} must contain exactly its required MVP nodes",
            )
        for local_key, expected_type in expected_nodes.items():
            node = nodes.get(local_key)
            if node is None or node.type != expected_type:
                raise StructuredPrototypeGenerationAssemblyError(
                    "generation_semantic_invalid",
                    f"generated page {page.page_key} is missing required {local_key}:{expected_type}",
                )
        if page.page_key == "purchase-list":
            table = nodes["request-table"]
            assert isinstance(table, GeneratedTableNodeV1)
            _require_exact(
                (column.key for column in table.columns),
                set(PROCUREMENT_REQUEST_TABLE_COLUMN_KEYS),
                "request table columns",
            )
        result[page.page_key] = page
    return result


def _runtime_payload() -> dict[str, object]:
    pages = {key: _id(seed) for key, seed in _PAGE_SEEDS.items()}
    nodes = {
        local_key: _node_id(page_key, local_key)
        for page_key, required in PROCUREMENT_REQUIRED_NODE_TYPES.items()
        for local_key in required
    }
    role_applicant = _id("role-applicant")
    role_manager = _id("role-manager")
    selected_request = _id("variable-selected")
    schema_request = _id("schema-request")
    schema_title = _id("schema-field-title")
    schema_amount = _id("schema-field-amount")
    schema_status = _id("schema-field-status")
    form_create = _id("form-create")
    form_title = _id("form-field-title")
    form_amount = _id("form-field-amount")
    null_value = {"type": "null"}
    pending_value = {"type": "enum", "value": "pending"}
    approved_value = {"type": "enum", "value": "approved"}
    selected_expression = {"kind": "variable", "variableId": selected_request}
    return {
        "runtimeSchemaVersion": 1,
        "pageIds": [pages[key] for key in PROCUREMENT_PAGE_KEYS],
        "roles": [
            {"id": role_applicant, "key": "applicant", "label": "申请人"},
            {"id": role_manager, "key": "manager", "label": "主管"},
        ],
        "variables": [
            {
                "id": selected_request,
                "key": "selected-request",
                "valueType": "entityRef",
                "nullable": True,
                "defaultValue": null_value,
            }
        ],
        "entitySchemas": [
            {
                "id": schema_request,
                "key": "purchase-request",
                "fields": [
                    {"id": schema_title, "key": "title", "valueType": "string", "nullable": False},
                    {
                        "id": schema_amount,
                        "key": "amount",
                        "valueType": "integer",
                        "nullable": False,
                    },
                    {"id": schema_status, "key": "status", "valueType": "enum", "nullable": False},
                ],
            }
        ],
        "forms": [
            {
                "id": form_create,
                "key": "create-purchase-request",
                "fields": [
                    {
                        "id": form_title,
                        "key": "title",
                        "valueType": "string",
                        "initialValue": {"type": "string", "value": ""},
                        "required": True,
                        "minInteger": None,
                    },
                    {
                        "id": form_amount,
                        "key": "amount",
                        "valueType": "integer",
                        "initialValue": {"type": "integer", "value": 0},
                        "required": True,
                        "minInteger": 1,
                    },
                ],
            }
        ],
        "viewBindings": [
            {
                "id": _id("binding-table"),
                "nodeId": nodes["request-table"],
                "target": "tableRows",
                "schemaId": schema_request,
                "sortFieldId": schema_title,
                "sortDirection": "asc",
            },
            {
                "id": _id("binding-detail-title"),
                "nodeId": nodes["detail-title"],
                "target": "textContent",
                "value": {
                    "kind": "entityField",
                    "entityRef": selected_expression,
                    "fieldId": schema_title,
                    "fallback": {"type": "string", "value": "尚未选择申请"},
                },
            },
            {
                "id": _id("binding-detail-status"),
                "nodeId": nodes["detail-status"],
                "target": "textContent",
                "value": {
                    "kind": "entityField",
                    "entityRef": selected_expression,
                    "fieldId": schema_status,
                    "fallback": {"type": "enum", "value": "not-selected"},
                },
            },
            {
                "id": _id("binding-approve-visible"),
                "nodeId": nodes["approve-request"],
                "target": "visibility",
                "predicate": {"kind": "roleIs", "roleId": role_manager},
            },
        ],
        "rules": [
            {
                "id": _id("rule-submit"),
                "key": "submit-request",
                "enabled": True,
                "trigger": {
                    "kind": "nodeEvent",
                    "nodeId": nodes["submit-request"],
                    "event": "submit",
                },
                "guard": {"kind": "roleIs", "roleId": role_applicant},
                "effects": [
                    {"kind": "validateForm", "formId": form_create},
                    {
                        "kind": "createEntity",
                        "schemaId": schema_request,
                        "resultVariableId": selected_request,
                        "values": [
                            {
                                "fieldId": schema_title,
                                "value": {
                                    "kind": "formField",
                                    "formId": form_create,
                                    "fieldId": form_title,
                                },
                            },
                            {
                                "fieldId": schema_amount,
                                "value": {
                                    "kind": "formField",
                                    "formId": form_create,
                                    "fieldId": form_amount,
                                },
                            },
                            {
                                "fieldId": schema_status,
                                "value": {"kind": "literal", "value": pending_value},
                            },
                        ],
                    },
                    {"kind": "navigate", "targetPageId": pages["purchase-detail"]},
                    {"kind": "notify", "level": "success", "message": "采购申请已提交"},
                ],
                "guardFalseEffects": [
                    {"kind": "notify", "level": "error", "message": "当前模拟角色不能提交申请"}
                ],
            },
            {
                "id": _id("rule-select"),
                "key": "select-request",
                "enabled": True,
                "trigger": {
                    "kind": "nodeEvent",
                    "nodeId": nodes["request-table"],
                    "event": "rowActivated",
                },
                "guard": None,
                "effects": [
                    {
                        "kind": "setVariable",
                        "variableId": selected_request,
                        "value": {"kind": "eventEntityRef"},
                    },
                    {"kind": "navigate", "targetPageId": pages["purchase-detail"]},
                ],
                "guardFalseEffects": [],
            },
            {
                "id": _id("rule-approve"),
                "key": "approve-request",
                "enabled": True,
                "trigger": {
                    "kind": "nodeEvent",
                    "nodeId": nodes["approve-request"],
                    "event": "click",
                },
                "guard": {
                    "kind": "all",
                    "items": [
                        {"kind": "roleIs", "roleId": role_manager},
                        {
                            "kind": "compare",
                            "operator": "eq",
                            "left": {
                                "kind": "entityField",
                                "entityRef": selected_expression,
                                "fieldId": schema_status,
                                "fallback": {"type": "enum", "value": "not-selected"},
                            },
                            "right": {"kind": "literal", "value": pending_value},
                        },
                    ],
                },
                "effects": [
                    {
                        "kind": "updateEntity",
                        "schemaId": schema_request,
                        "entityRef": selected_expression,
                        "updates": [
                            {
                                "fieldId": schema_status,
                                "value": {"kind": "literal", "value": approved_value},
                            }
                        ],
                    },
                    {"kind": "notify", "level": "success", "message": "采购申请已审批通过"},
                ],
                "guardFalseEffects": [
                    {"kind": "notify", "level": "error", "message": "当前申请不能审批"}
                ],
            },
        ],
        "scenarios": [
            {
                "id": _id("scenario-happy-path"),
                "key": "purchase-approval-happy-path",
                "actorRoleId": role_applicant,
                "startPageId": pages["purchase-create"],
                "initialVariables": [{"variableId": selected_request, "value": null_value}],
                "entityFixtures": [],
                "allowSimulatedRoleSwitch": True,
            }
        ],
    }


def assemble_procurement_candidate(
    *,
    document_id: str,
    blueprint: GenerationBlueprintV1,
    foundation: GenerationFoundationV1,
    pages: tuple[GeneratedPageV1, ...],
) -> PrototypeDocumentV1:
    _validate_blueprint(blueprint)
    _validate_foundation(foundation)
    page_by_key = _validate_pages(blueprint, pages)
    blueprint_by_key = {page.page_key: page for page in blueprint.pages}
    navigation_by_page = {item.target_page_key: item for item in blueprint.navigation}
    page_ids = {key: _id(seed) for key, seed in _PAGE_SEEDS.items()}
    document_pages: list[dict[str, object]] = []
    for page_key in PROCUREMENT_PAGE_KEYS:
        generated = page_by_key[page_key]
        root = _convert_node(page_key, generated.root)
        root["id"] = _id(_ROOT_SEEDS[page_key])
        confirmed = blueprint_by_key[page_key]
        document_pages.append(
            {
                "id": page_ids[page_key],
                "key": page_key,
                "title": confirmed.title,
                "route": confirmed.route,
                "viewport": {"width": 1440, "height": 900},
                "root": root,
            }
        )
    payload = {
        "schemaVersion": 1,
        "id": document_id,
        "title": blueprint.document_title,
        "locale": blueprint.output_locale,
        "settings": {"defaultViewport": "desktop", "theme": "light"},
        "tokens": {
            "colors": [token.model_dump(mode="json", by_alias=True) for token in foundation.colors],
            "spacing": [
                token.model_dump(mode="json", by_alias=True) for token in foundation.spacing
            ],
        },
        "componentDefinitions": [],
        "pages": document_pages,
        "navigation": {
            "items": [
                {
                    "id": _id(f"nav-{page_key.removeprefix('purchase-')}"),
                    "key": page_key,
                    "label": navigation_by_page[page_key].label,
                    "targetPageId": page_ids[page_key],
                }
                for page_key in PROCUREMENT_PAGE_KEYS
            ]
        },
        "flows": [
            {
                "id": _id("flow-submit"),
                "key": "submit-request",
                "ruleId": _id("rule-submit"),
                "fromNodeId": _node_id("purchase-create", "submit-request"),
                "toPageId": page_ids["purchase-detail"],
            },
            {
                "id": _id("flow-select"),
                "key": "select-request",
                "ruleId": _id("rule-select"),
                "fromNodeId": _node_id("purchase-list", "request-table"),
                "toPageId": page_ids["purchase-detail"],
            },
            {
                "id": _id("flow-approve"),
                "key": "approve-request",
                "ruleId": _id("rule-approve"),
                "fromNodeId": _node_id("purchase-detail", "approve-request"),
                "toPageId": page_ids["purchase-detail"],
            },
        ],
        "runtime": _runtime_payload(),
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
            "assembled procurement document does not satisfy the canonical contract",
        ) from exc
