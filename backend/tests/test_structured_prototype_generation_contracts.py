from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.application.structured_prototype_contracts import StructuredPrototypeContractError
from app.application.structured_prototype_generation_contracts import (
    GeneratedGridNodeV1,
    GeneratedPageV1,
    GeneratedTableNodeV1,
    GenerationBlueprintV1,
    GenerationFoundationV1,
    parse_generation_artifact,
)


def blueprint_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "documentTitle": "Northstar 管理后台",
        "productIntent": "查看运营指标并管理用户和订单",
        "outputLocale": "zh-CN",
        "foundationIntent": {
            "visualLanguage": "安静、紧凑的后台管理工作台",
            "density": "compact",
            "responsiveStrategy": "移动端单列并在桌面端保持信息密度",
        },
        "pages": [
            {
                "pageKey": "dashboard",
                "title": "仪表盘",
                "route": "/dashboard",
                "purpose": "查看关键运营指标",
                "navigationGroupKey": "main",
            },
            {
                "pageKey": "users",
                "title": "用户管理",
                "route": "/users",
                "purpose": "查看平台用户及状态",
                "navigationGroupKey": "main",
            },
            {
                "pageKey": "orders",
                "title": "订单管理",
                "route": "/orders",
                "purpose": "查看订单金额与履约状态",
                "navigationGroupKey": "main",
            },
        ],
        "navigation": [
            {"key": "dashboard", "label": "仪表盘", "targetPageKey": "dashboard"},
            {"key": "users", "label": "用户管理", "targetPageKey": "users"},
            {"key": "orders", "label": "订单管理", "targetPageKey": "orders"},
        ],
        "flowIntents": [
            {
                "key": "dashboard-to-users",
                "sourcePageKey": "dashboard",
                "behaviorIntentKey": "open-users",
                "targetPageKey": "users",
            }
        ],
        "roleIntents": [{"key": "operator", "label": "运营人员"}],
        "entityIntents": [
            {
                "key": "user",
                "fields": [
                    {"key": "name", "valueType": "string", "nullable": False},
                    {"key": "email", "valueType": "string", "nullable": False},
                    {"key": "status", "valueType": "enum", "nullable": False},
                ],
            },
            {
                "key": "order",
                "fields": [
                    {"key": "number", "valueType": "string", "nullable": False},
                    {"key": "customer", "valueType": "string", "nullable": False},
                    {"key": "amount", "valueType": "integer", "nullable": False},
                    {"key": "status", "valueType": "enum", "nullable": False},
                ],
            },
        ],
        "variableIntents": [],
        "formIntents": [],
        "viewBindingIntents": [
            {
                "key": "users-table-rows",
                "pageKey": "users",
                "target": "tableRows",
                "schemaKey": "user",
                "sortFieldKey": "name",
                "sortDirection": "asc",
            },
            {
                "key": "orders-table-rows",
                "pageKey": "orders",
                "target": "tableRows",
                "schemaKey": "order",
                "sortFieldKey": "number",
                "sortDirection": "asc",
            },
        ],
        "behaviorIntents": [
            {
                "key": "open-users",
                "sourcePageKey": "dashboard",
                "guard": None,
                "effects": [{"kind": "navigate", "targetPageKey": "users"}],
                "guardFalseEffects": [],
            }
        ],
        "scenarioIntents": [
            {
                "key": "admin-overview",
                "actorRoleKey": "operator",
                "startPageKey": "dashboard",
                "initialVariables": [],
                "entityFixtures": [
                    {
                        "schemaKey": "user",
                        "entities": [
                            {
                                "key": "alice",
                                "fields": [
                                    {
                                        "fieldKey": "name",
                                        "value": {"type": "string", "value": "Alice Chen"},
                                    },
                                    {
                                        "fieldKey": "email",
                                        "value": {
                                            "type": "string",
                                            "value": "alice@example.com",
                                        },
                                    },
                                    {
                                        "fieldKey": "status",
                                        "value": {"type": "enum", "value": "active"},
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "schemaKey": "order",
                        "entities": [
                            {
                                "key": "order-1042",
                                "fields": [
                                    {
                                        "fieldKey": "number",
                                        "value": {"type": "string", "value": "NS-1042"},
                                    },
                                    {
                                        "fieldKey": "customer",
                                        "value": {"type": "string", "value": "Acme"},
                                    },
                                    {
                                        "fieldKey": "amount",
                                        "value": {"type": "integer", "value": 6800},
                                    },
                                    {
                                        "fieldKey": "status",
                                        "value": {"type": "enum", "value": "paid"},
                                    },
                                ],
                            }
                        ],
                    },
                ],
                "allowSimulatedRoleSwitch": False,
                "scriptedSteps": [
                    {
                        "kind": "activateBehavior",
                        "behaviorIntentKey": "open-users",
                        "expectedOutcome": "applied",
                    }
                ],
                "milestones": [
                    {
                        "afterStep": 1,
                        "currentPageKey": "users",
                        "variableValues": [],
                        "entityFieldValues": [],
                    }
                ],
            }
        ],
        "startPageKeys": ["dashboard"],
    }


def foundation_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "colors": [
            {"key": "primary", "value": "#126b5f"},
            {"key": "surface", "value": "#ffffff"},
        ],
        "spacing": [{"key": "panel-gap", "value": "16px"}],
        "sharedShell": {
            "kind": "sidebar",
            "title": "Northstar 管理后台",
            "accentColorTokenKey": "primary",
            "navigationBackgroundColorTokenKey": "surface",
            "contentBackgroundColorTokenKey": "surface",
            "surfaceColorTokenKey": "surface",
            "navigationWidth": 240,
            "expandedMinWidth": 1024,
        },
        "contentConventions": "使用清晰、简短的后台管理文案",
    }


def dashboard_page_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "pageKey": "dashboard",
        "title": "仪表盘",
        "route": "/dashboard",
        "root": {
            "localKey": "dashboard-root",
            "name": "仪表盘页面",
            "type": "Stack",
            "direction": "column",
            "gap": 16,
            "padding": 24,
            "children": [
                {
                    "localKey": "dashboard-title",
                    "name": "仪表盘标题",
                    "type": "Text",
                    "content": "运营概览",
                    "semantic": "heading",
                    "tone": "default",
                },
                {
                    "localKey": "open-users",
                    "name": "查看用户",
                    "type": "Button",
                    "label": "查看用户",
                    "variant": "primary",
                },
            ],
        },
        "formBindings": [],
        "viewBindings": [],
        "behaviorBindings": [
            {
                "sourceNodeKey": "open-users",
                "event": "click",
                "behaviorIntentKey": "open-users",
            }
        ],
    }


def users_page_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "pageKey": "users",
        "title": "用户管理",
        "route": "/users",
        "root": {
            "localKey": "users-root",
            "name": "用户管理页面",
            "type": "Stack",
            "direction": "column",
            "gap": 16,
            "padding": 24,
            "children": [
                {
                    "localKey": "users-title",
                    "name": "用户管理标题",
                    "type": "Text",
                    "content": "用户管理",
                    "semantic": "heading",
                    "tone": "default",
                },
                {
                    "localKey": "users-table",
                    "name": "用户列表",
                    "type": "Table",
                    "columns": [
                        {"key": "name", "label": "姓名"},
                        {"key": "email", "label": "邮箱"},
                        {"key": "status", "label": "状态"},
                    ],
                    "rows": [],
                    "density": "compact",
                },
            ],
        },
        "formBindings": [],
        "viewBindings": [{"nodeKey": "users-table", "viewBindingIntentKey": "users-table-rows"}],
        "behaviorBindings": [],
    }


def orders_page_payload() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "pageKey": "orders",
        "title": "订单管理",
        "route": "/orders",
        "root": {
            "localKey": "orders-root",
            "name": "订单管理页面",
            "type": "Stack",
            "direction": "column",
            "gap": 16,
            "padding": 24,
            "children": [
                {
                    "localKey": "orders-title",
                    "name": "订单管理标题",
                    "type": "Text",
                    "content": "订单管理",
                    "semantic": "heading",
                    "tone": "default",
                },
                {
                    "localKey": "orders-table",
                    "name": "订单列表",
                    "type": "Table",
                    "columns": [
                        {"key": "number", "label": "订单号"},
                        {"key": "customer", "label": "客户"},
                        {"key": "amount", "label": "金额"},
                        {"key": "status", "label": "状态"},
                    ],
                    "rows": [],
                    "density": "compact",
                },
            ],
        },
        "formBindings": [],
        "viewBindings": [{"nodeKey": "orders-table", "viewBindingIntentKey": "orders-table-rows"}],
        "behaviorBindings": [],
    }


def page_payload() -> dict[str, object]:
    return dashboard_page_payload()


def users_table_payload(payload: dict[str, object]) -> dict[str, object]:
    root = payload["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    table = children[1]
    assert isinstance(table, dict)
    return table


def interactive_blueprint_payload() -> dict[str, object]:
    payload = blueprint_payload()
    payload["variableIntents"] = [
        {
            "key": "selected-user",
            "valueType": "entityRef",
            "nullable": True,
            "entitySchemaKey": "user",
            "defaultValue": {"type": "null"},
        }
    ]
    payload["formIntents"] = [
        {
            "key": "user-filter",
            "pageKey": "users",
            "fields": [
                {
                    "key": "query",
                    "valueType": "string",
                    "initialValue": {"type": "string", "value": ""},
                    "required": False,
                    "minInteger": None,
                }
            ],
        }
    ]
    scenarios = payload["scenarioIntents"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    scenario["initialVariables"] = [{"variableKey": "selected-user", "value": {"type": "null"}}]
    steps = scenario["scriptedSteps"]
    assert isinstance(steps, list)
    steps.append(
        {
            "kind": "commitFormField",
            "pageKey": "users",
            "formKey": "user-filter",
            "fieldKey": "query",
            "value": {"type": "string", "value": "Alice"},
            "expectedOutcome": "applied",
        }
    )
    scenario["milestones"] = [
        {
            "afterStep": 2,
            "currentPageKey": "users",
            "variableValues": [{"variableKey": "selected-user", "value": {"type": "null"}}],
            "entityFieldValues": [
                {
                    "schemaKey": "user",
                    "entityKey": "alice",
                    "fieldKey": "name",
                    "value": {"type": "string", "value": "Alice Chen"},
                }
            ],
        }
    ]
    return payload


def branching_blueprint_payload() -> dict[str, object]:
    payload = blueprint_payload()
    behaviors = payload["behaviorIntents"]
    assert isinstance(behaviors, list)
    behavior = behaviors[0]
    assert isinstance(behavior, dict)
    behavior["guard"] = {"kind": "roleIs", "roleKey": "operator"}
    behavior["guardFalseEffects"] = [{"kind": "navigate", "targetPageKey": "orders"}]
    flows = payload["flowIntents"]
    assert isinstance(flows, list)
    flows.append(
        {
            "key": "dashboard-to-orders",
            "sourcePageKey": "dashboard",
            "behaviorIntentKey": "open-users",
            "targetPageKey": "orders",
        }
    )
    return payload


def test_generation_contracts_accept_strict_admin_demo_artifacts() -> None:
    blueprint = GenerationBlueprintV1.model_validate(blueprint_payload(), strict=True)
    foundation = GenerationFoundationV1.model_validate(foundation_payload(), strict=True)
    page = GeneratedPageV1.model_validate(page_payload(), strict=True)

    assert [item.page_key for item in blueprint.pages] == ["dashboard", "users", "orders"]
    assert [item.key for item in blueprint.entity_intents] == ["user", "order"]
    assert page.behavior_bindings[0].behavior_intent_key == "open-users"
    assert foundation.shared_shell.title == "Northstar 管理后台"


def test_generated_grid_accepts_ordered_responsive_columns() -> None:
    payload = page_payload()
    root = payload["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    children.append(
        {
            "localKey": "metric-grid",
            "name": "指标网格",
            "type": "Grid",
            "columns": 1,
            "gap": 16,
            "padding": 0,
            "columnOverrides": [
                {"minWidth": 768, "columns": 2},
                {"minWidth": 1200, "columns": 4},
            ],
            "children": [],
        }
    )

    page = GeneratedPageV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )

    grid = page.root.children[-1]
    assert isinstance(grid, GeneratedGridNodeV1)
    assert [(item.min_width, item.columns) for item in grid.column_overrides] == [
        (768, 2),
        (1200, 4),
    ]


def test_generated_grid_refuses_unsorted_or_misspelled_column_overrides() -> None:
    payload = page_payload()
    root = payload["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    grid = {
        "localKey": "metric-grid",
        "name": "指标网格",
        "type": "Grid",
        "columns": 1,
        "gap": 16,
        "padding": 0,
        "columnOverrides": [
            {"minWidth": 1200, "columns": 4},
            {"minWidth": 768, "columns": 2},
        ],
        "children": [],
    }
    children.append(grid)

    with pytest.raises(ValueError, match="strictly increasing"):
        GeneratedPageV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    grid["column_overrides"] = grid.pop("columnOverrides")
    with pytest.raises(ValueError):
        GeneratedPageV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_foundation_refuses_unknown_shell_color_token() -> None:
    payload = foundation_payload()
    shell = payload["sharedShell"]
    assert isinstance(shell, dict)
    shell["accentColorTokenKey"] = "missing"

    with pytest.raises(ValueError, match="unknown color token"):
        GenerationFoundationV1.model_validate(payload, strict=True)


@pytest.mark.parametrize("duplicate_field", ["roleIntents", "startPageKeys"])
def test_blueprint_refuses_duplicate_semantic_keys(duplicate_field: str) -> None:
    payload = blueprint_payload()
    values = payload[duplicate_field]
    assert isinstance(values, list)
    values.append(deepcopy(values[0]))

    with pytest.raises(ValueError, match="duplicate"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_blueprint_refuses_an_unknown_intent_page() -> None:
    payload = blueprint_payload()
    bindings = payload["viewBindingIntents"]
    assert isinstance(bindings, list)
    binding = bindings[0]
    assert isinstance(binding, dict)
    binding["pageKey"] = "missing-page"

    with pytest.raises(ValueError, match="view-binding page must exist"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_blueprint_refuses_flow_and_behavior_source_page_drift() -> None:
    payload = blueprint_payload()
    behaviors = payload["behaviorIntents"]
    assert isinstance(behaviors, list)
    behavior = behaviors[0]
    assert isinstance(behavior, dict)
    behavior["sourcePageKey"] = "users"

    with pytest.raises(ValueError, match="flow and behavior source pages must match"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_blueprint_refuses_flow_and_behavior_target_page_drift() -> None:
    payload = blueprint_payload()
    flows = payload["flowIntents"]
    assert isinstance(flows, list)
    flow = flows[0]
    assert isinstance(flow, dict)
    flow["targetPageKey"] = "orders"

    with pytest.raises(ValueError, match="flow targets must exactly match"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_blueprint_projects_each_behavior_navigation_target_to_a_distinct_flow() -> None:
    blueprint = GenerationBlueprintV1.model_validate(branching_blueprint_payload(), strict=True)

    assert [flow.target_page_key for flow in blueprint.flow_intents] == ["users", "orders"]


def test_blueprint_refuses_an_incomplete_behavior_navigation_projection() -> None:
    payload = branching_blueprint_payload()
    flows = payload["flowIntents"]
    assert isinstance(flows, list)
    flows.pop()

    with pytest.raises(ValueError, match="flow targets must exactly match"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_blueprint_refuses_a_duplicate_behavior_target_projection() -> None:
    payload = blueprint_payload()
    flows = payload["flowIntents"]
    assert isinstance(flows, list)
    duplicate = deepcopy(flows[0])
    assert isinstance(duplicate, dict)
    duplicate["key"] = "dashboard-to-users-copy"
    flows.append(duplicate)

    with pytest.raises(ValueError, match="duplicate flow behavior target"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_blueprint_advances_scenario_reachability_after_navigation() -> None:
    GenerationBlueprintV1.model_validate(interactive_blueprint_payload(), strict=True)


def test_blueprint_keeps_each_branch_target_reachable_for_a_scenario_milestone() -> None:
    payload = branching_blueprint_payload()
    scenarios = payload["scenarioIntents"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    milestones = scenario["milestones"]
    assert isinstance(milestones, list)
    milestone = milestones[0]
    assert isinstance(milestone, dict)
    milestone["currentPageKey"] = "orders"

    GenerationBlueprintV1.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("after_step", "page_key"),
    [(0, "users"), (1, "dashboard")],
)
def test_blueprint_refuses_a_milestone_page_unreachable_after_its_step(
    after_step: int,
    page_key: str,
) -> None:
    payload = blueprint_payload()
    scenarios = payload["scenarioIntents"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    milestones = scenario["milestones"]
    assert isinstance(milestones, list)
    milestone = milestones[0]
    assert isinstance(milestone, dict)
    milestone["afterStep"] = after_step
    milestone["currentPageKey"] = page_key

    with pytest.raises(ValueError, match="milestone page must be reachable after its step"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_blueprint_refuses_behavior_activation_from_an_unreachable_page() -> None:
    payload = blueprint_payload()
    scenarios = payload["scenarioIntents"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    scenario["startPageKey"] = "orders"

    with pytest.raises(ValueError, match="behavior source page must be currently reachable"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("broken_reference", "message"),
    [
        ("milestone-page", "milestone page must exist"),
        ("milestone-variable", "milestone variable must exist"),
        ("milestone-schema", "milestone entity schema must exist"),
        ("milestone-entity", "milestone entity fixture must exist"),
        ("milestone-field", "milestone entity field must exist"),
        ("form-step-field", "form step field must exist"),
        ("fixture-field", "fixture fields must match its schema"),
    ],
)
def test_blueprint_refuses_nested_scenario_references(
    broken_reference: str,
    message: str,
) -> None:
    payload = interactive_blueprint_payload()
    scenarios = payload["scenarioIntents"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    milestones = scenario["milestones"]
    assert isinstance(milestones, list)
    milestone = milestones[0]
    assert isinstance(milestone, dict)
    entity_values = milestone["entityFieldValues"]
    assert isinstance(entity_values, list)
    entity_value = entity_values[0]
    assert isinstance(entity_value, dict)
    if broken_reference == "milestone-page":
        milestone["currentPageKey"] = "missing-page"
    elif broken_reference == "milestone-variable":
        variable_values = milestone["variableValues"]
        assert isinstance(variable_values, list)
        variable_value = variable_values[0]
        assert isinstance(variable_value, dict)
        variable_value["variableKey"] = "missing-variable"
    elif broken_reference == "milestone-schema":
        entity_value["schemaKey"] = "missing-schema"
    elif broken_reference == "milestone-entity":
        entity_value["entityKey"] = "missing-entity"
    elif broken_reference == "milestone-field":
        entity_value["fieldKey"] = "missing-field"
    elif broken_reference == "form-step-field":
        steps = scenario["scriptedSteps"]
        assert isinstance(steps, list)
        step = steps[1]
        assert isinstance(step, dict)
        step["fieldKey"] = "missing-field"
    else:
        fixtures = scenario["entityFixtures"]
        assert isinstance(fixtures, list)
        fixture_set = fixtures[0]
        assert isinstance(fixture_set, dict)
        entities = fixture_set["entities"]
        assert isinstance(entities, list)
        entity = entities[0]
        assert isinstance(entity, dict)
        fields = entity["fields"]
        assert isinstance(fields, list)
        field = fields[0]
        assert isinstance(field, dict)
        field["fieldKey"] = "missing-field"

    with pytest.raises(ValueError, match=message):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_blueprint_refuses_nested_view_and_effect_references() -> None:
    payload = interactive_blueprint_payload()
    bindings = payload["viewBindingIntents"]
    assert isinstance(bindings, list)
    binding = bindings[0]
    assert isinstance(binding, dict)
    binding["sortFieldKey"] = "missing-field"

    with pytest.raises(ValueError, match="table binding sort field must exist"):
        GenerationBlueprintV1.model_validate(payload, strict=True)

    payload = interactive_blueprint_payload()
    behaviors = payload["behaviorIntents"]
    assert isinstance(behaviors, list)
    behavior = behaviors[0]
    assert isinstance(behavior, dict)
    behavior["guard"] = {"kind": "formValid", "formKey": "missing-form"}

    with pytest.raises(ValueError, match="predicate form must exist"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_foundation_refuses_duplicate_token_key() -> None:
    payload = foundation_payload()
    colors = payload["colors"]
    assert isinstance(colors, list)
    colors.append(deepcopy(colors[0]))

    with pytest.raises(ValueError, match="duplicate color token key"):
        GenerationFoundationV1.model_validate(payload, strict=True)


def test_foundation_refuses_css_shorthand_spacing_token() -> None:
    payload = foundation_payload()
    spacing = payload["spacing"]
    assert isinstance(spacing, list)
    token = spacing[0]
    assert isinstance(token, dict)
    token["value"] = "34px 32px 48px"

    with pytest.raises(ValueError):
        GenerationFoundationV1.model_validate(payload, strict=True)


def test_page_refuses_duplicate_local_key_anywhere_in_tree() -> None:
    payload = page_payload()
    root = payload["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    children.append(deepcopy(children[0]))

    with pytest.raises(ValueError, match="duplicate page node local key"):
        GeneratedPageV1.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    "children",
    [
        [],
        [
            {
                "localKey": "hidden-title",
                "name": "隐藏标题",
                "type": "Text",
                "visibility": "hidden",
                "content": "隐藏内容",
                "semantic": "heading",
                "tone": "default",
            }
        ],
        [
            {
                "localKey": "empty-grid",
                "name": "空网格",
                "type": "Grid",
                "columns": 2,
                "gap": 16,
                "padding": 0,
                "columnOverrides": [],
                "children": [],
            }
        ],
    ],
)
def test_page_refuses_empty_visible_content_subtree(
    children: list[dict[str, object]],
) -> None:
    payload = page_payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["children"] = children

    with pytest.raises(ValueError, match="at least one visible content node"):
        GeneratedPageV1.model_validate(payload, strict=True)


def test_page_accepts_complete_static_table_rows() -> None:
    payload = users_page_payload()
    table = users_table_payload(payload)
    table["rows"] = [
        {
            "localKey": "alice",
            "cells": [
                {"columnKey": "name", "value": "Alice Chen"},
                {"columnKey": "email", "value": "alice@example.com"},
                {"columnKey": "status", "value": "Active"},
            ],
        }
    ]

    page = GeneratedPageV1.model_validate(payload, strict=True)

    table_node = page.root.children[1]
    assert isinstance(table_node, GeneratedTableNodeV1)
    assert table_node.rows[0].local_key == "alice"


@pytest.mark.parametrize(
    ("violation", "message"),
    [
        ("duplicate-row", "duplicate table row local key"),
        ("duplicate-cell", "duplicate table cell column key"),
        ("missing-column", "cells must match the table columns"),
        ("unknown-column", "cells must match the table columns"),
        ("duplicate-column", "duplicate table column key"),
    ],
)
def test_page_refuses_invalid_static_table_shape(violation: str, message: str) -> None:
    payload = users_page_payload()
    table = users_table_payload(payload)
    row = {
        "localKey": "alice",
        "cells": [
            {"columnKey": "name", "value": "Alice Chen"},
            {"columnKey": "email", "value": "alice@example.com"},
            {"columnKey": "status", "value": "Active"},
        ],
    }
    rows = [row]
    table["rows"] = rows
    if violation == "duplicate-row":
        rows.append(deepcopy(row))
    elif violation == "duplicate-cell":
        cells = row["cells"]
        assert isinstance(cells, list)
        cells.append({"columnKey": "name", "value": "Duplicate"})
    elif violation == "missing-column":
        cells = row["cells"]
        assert isinstance(cells, list)
        cells.pop()
    elif violation == "unknown-column":
        cells = row["cells"]
        assert isinstance(cells, list)
        cells.append({"columnKey": "unknown", "value": "Unexpected"})
    else:
        columns = table["columns"]
        assert isinstance(columns, list)
        columns.append(deepcopy(columns[0]))

    with pytest.raises(ValueError, match=message):
        GeneratedPageV1.model_validate(payload, strict=True)


def test_artifact_parser_refuses_unknown_fields() -> None:
    envelope = {
        "generationContractVersion": 3,
        "jobId": "job-1",
        "runId": "run-1",
        "itemId": "item-1",
        "taskKind": "generation_blueprint",
        "contextObjectHash": "sha256:" + "a" * 64,
        "payload": blueprint_payload(),
        "unexpected": True,
    }

    with pytest.raises(StructuredPrototypeContractError) as error:
        parse_generation_artifact("generation_blueprint", json.dumps(envelope).encode())
    assert error.value.code == "schema_invalid"
