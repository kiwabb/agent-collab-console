from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError
from structured_prototype_fixtures import (
    fixture_id,
    procurement_document,
    procurement_document_payload,
)

import app.application.structured_prototype_contracts as prototype_contracts
from app.adapters.prototype_object_store import canonical_json_bytes
from app.application.structured_prototype_contracts import (
    CommandHistoryCheckpointV1,
    DomainCommandBatchV1,
    FormNodeV1,
    FreeformNodeV1,
    GridNodeV1,
    InverseCommandBatchV1,
    PrototypeDocumentV1,
    StackNodeV1,
    StructuredPrototypeContractError,
    advance_journal_prefix_hash,
    apply_inverse_commands,
    canonical_command_history_checkpoint_json,
    command_batch_envelope_hash,
    command_batch_hash,
    command_history_checkpoint_from_domain,
    command_history_checkpoint_to_domain,
    document_hash,
    execute_command_batch,
    execute_inverse_command_batch,
    freeform_grid_list_hash,
    initial_journal_prefix_hash,
    parse_command_batch_json,
    parse_command_history_checkpoint_json,
    parse_prototype_document_json,
    validate_command_batch_evidence_context,
)
from app.domain.structured_prototype import (
    PrototypeCommandBatchRecord,
    PrototypeCommandHistory,
    PrototypeCommandHistoryEntry,
    fold_prototype_command_history,
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


def _freeform_document_payload() -> dict[str, object]:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    list_page = pages[0]
    assert isinstance(list_page, dict)
    original_root = list_page["root"]
    assert isinstance(original_root, dict)
    children = original_root["children"]
    assert isinstance(children, list)
    for index, child in enumerate(children):
        assert isinstance(child, dict)
        layout_item = child["layoutItem"]
        assert isinstance(layout_item, dict)
        layout_item["position"] = {"x": str(32 + index * 360), "y": "48"}

    root_layout = _layout()
    root_layout["width"] = {"unit": "px", "value": "1200"}
    root_layout["height"] = {"unit": "px", "value": "800"}
    list_page["root"] = {
        "id": original_root["id"],
        "type": "Freeform",
        "name": original_root["name"],
        "visibility": original_root["visibility"],
        "layoutItem": root_layout,
        "responsive": [],
        "children": children,
    }
    return payload


def _ordinary_positioned_document() -> PrototypeDocumentV1:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    page = pages[0]
    assert isinstance(page, dict)
    root = page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    title = children[0]
    assert isinstance(title, dict)
    layout_item = title["layoutItem"]
    assert isinstance(layout_item, dict)
    layout_item["position"] = {"x": "12", "y": "24"}
    return PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _freeform_root(payload: dict[str, object]) -> dict[str, object]:
    pages = payload["pages"]
    assert isinstance(pages, list)
    page = pages[0]
    assert isinstance(page, dict)
    root = page["root"]
    assert isinstance(root, dict)
    assert root["type"] == "Freeform"
    return root


def _square_freeform_grid(key: str) -> dict[str, object]:
    return {
        "id": fixture_id(key),
        "version": 1,
        "type": "square",
        "visible": True,
        "snapEnabled": True,
        "origin": {"x": "0", "y": "0"},
        "params": {
            "size": "16",
            "colorTokenKey": "primary",
            "opacity": "0.24",
        },
    }


def _columns_freeform_grid(key: str) -> dict[str, object]:
    return {
        "id": fixture_id(key),
        "version": 1,
        "type": "columns",
        "visible": True,
        "snapEnabled": True,
        "origin": {"x": "0", "y": "0"},
        "params": {
            "count": 12,
            "itemSize": None,
            "gutter": "8",
            "margin": "24",
            "alignment": "stretch",
            "colorTokenKey": "primary",
            "opacity": "0.18",
        },
    }


def _rows_freeform_grid(key: str) -> dict[str, object]:
    return {
        "id": fixture_id(key),
        "version": 1,
        "type": "rows",
        "visible": True,
        "snapEnabled": True,
        "origin": {"x": "0", "y": "0"},
        "params": {
            "count": 8,
            "itemSize": "72",
            "gutter": "12",
            "margin": "24",
            "alignment": "start",
            "colorTokenKey": "primary",
            "opacity": "0.18",
        },
    }


def _freeform_move_evidence_payload() -> dict[str, object]:
    grid = _square_freeform_grid("move-evidence-grid")
    sibling_id = fixture_id("table-list")
    second_sibling_id = fixture_id("move-evidence-sibling-2")
    return {
        "evidenceVersion": 2,
        "kind": "freeformMove",
        "snapSolverVersion": "structured-prototype-freeform-snap/v1",
        "snapSolverSourceHash": _hash("f"),
        "documentId": fixture_id("document"),
        "draftId": fixture_id("move-evidence-draft"),
        "freeformId": fixture_id("root-list"),
        "baseHeadSequenceNo": 12,
        "baseDocumentHash": _hash("a"),
        "selectedNodeIds": [fixture_id("title-list")],
        "grids": [grid],
        "gridListHash": _hash("b"),
        "gridSnappingEnabled": True,
        "previewScale": "1.25",
        "clientThreshold": "6",
        "selectionBounds": {"x": "32", "y": "48", "width": "300", "height": "40"},
        "directSiblings": [
            {
                "nodeId": second_sibling_id,
                "x": "800",
                "y": "48",
                "width": "200",
                "height": "320",
            },
            {
                "nodeId": sibling_id,
                "x": "40",
                "y": "48",
                "width": "600",
                "height": "320",
            },
        ],
        "containerSize": {"width": "1200", "height": "800"},
        "requestedDelta": {"x": "5", "y": "3"},
        "rawPosition": {"x": "37", "y": "51"},
        "finalPosition": {"x": "40", "y": "48"},
        "correction": {"x": "3", "y": "-3"},
        "bypassSnapping": False,
        "axisWinners": {"x": "alignment", "y": "grid"},
        "candidates": [
            {
                "source": "alignment",
                "axis": "x",
                "position": "40",
                "correction": "3",
                "distance": "3",
                "sortKey": "0:alignment:table-list:left",
                "outcome": "winner",
                "coordinate": "40",
                "movingAnchor": "left",
                "targetAnchor": "left",
                "targetKind": "sibling",
                "targetNodeId": sibling_id,
            },
            {
                "source": "spacing",
                "axis": "x",
                "position": "42",
                "correction": "5",
                "distance": "5",
                "sortKey": "1:spacing:between:table-list:second",
                "outcome": "farther",
                "placement": "between",
                "gap": "16",
                "referenceNodeIds": [sibling_id, second_sibling_id],
            },
            {
                "source": "grid",
                "axis": "y",
                "position": "48",
                "correction": "-3",
                "distance": "3",
                "sortKey": "2:grid:move-evidence-grid:3:top",
                "outcome": "winner",
                "gridId": grid["id"],
                "gridType": "square",
                "gridLineIndex": 3,
                "coordinate": "48",
                "movingAnchor": "top",
            },
        ],
        "terminalReason": "pointerup",
    }


def _freeform_move_evidence_batch_payload() -> dict[str, object]:
    return {
        "commandContractVersion": 1,
        "summary": "移动自由布局组件",
        "commands": [
            {
                "kind": "moveNode",
                "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                "targetParent": {"kind": "existing", "nodeId": fixture_id("root-list")},
                "targetSlot": None,
                "targetIndex": 0,
                "targetPosition": {"x": "40", "y": "48"},
            }
        ],
        "evidence": _freeform_move_evidence_payload(),
    }


def _freeform_move_context_payload(
    *,
    group: bool = False,
) -> tuple[PrototypeDocumentV1, dict[str, object]]:
    document_payload = _freeform_document_payload()
    root_payload = _freeform_root(document_payload)
    root_payload["grids"] = [
        _square_freeform_grid("move-evidence-grid"),
        _columns_freeform_grid("move-evidence-columns-grid"),
    ]
    document = PrototypeDocumentV1.model_validate(
        document_payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    root = document.pages[0].root
    assert isinstance(root, FreeformNodeV1)
    selected = list(root.children) if group else [root.children[0]]
    selected_ids = sorted(node.id for node in selected)
    selected_id_set = set(selected_ids)
    index_by_id = {node.id: index for index, node in enumerate(root.children)}
    commands: list[dict[str, object]] = []
    for node in selected:
        position = node.layout_item.position
        assert position is not None
        commands.append(
            {
                "kind": "moveNode",
                "node": {"kind": "existing", "nodeId": node.id},
                "targetParent": {"kind": "existing", "nodeId": root.id},
                "targetSlot": None,
                "targetIndex": index_by_id[node.id],
                "targetPosition": {
                    "x": str(Decimal(position.x) + Decimal("8")),
                    "y": str(Decimal(position.y) + Decimal("4")),
                },
            }
        )
    siblings = []
    for node in root.children:
        if node.id in selected_id_set:
            continue
        position = node.layout_item.position
        assert position is not None
        siblings.append(
            {
                "nodeId": node.id,
                "x": position.x,
                "y": position.y,
                "width": "600",
                "height": "320",
            }
        )
    siblings.sort(key=lambda sibling: str(sibling["nodeId"]))
    grids = [grid.model_dump(mode="json", by_alias=True) for grid in root.grids]
    return document, {
        "commandContractVersion": 1,
        "summary": "移动自由布局组件",
        "commands": commands,
        "evidence": {
            "evidenceVersion": 2,
            "kind": "freeformMove",
            "snapSolverVersion": "structured-prototype-freeform-snap/v1",
            "snapSolverSourceHash": _hash("f"),
            "documentId": document.id,
            "draftId": fixture_id("move-context-draft"),
            "freeformId": root.id,
            "baseHeadSequenceNo": 3,
            "baseDocumentHash": document_hash(document),
            "selectedNodeIds": selected_ids,
            "grids": grids,
            "gridListHash": freeform_grid_list_hash(root.grids),
            "gridSnappingEnabled": True,
            "previewScale": "1",
            "clientThreshold": "6",
            "selectionBounds": {
                "x": "32",
                "y": "48",
                "width": "960" if group else "300",
                "height": "320" if group else "40",
            },
            "directSiblings": siblings,
            "containerSize": {"width": "1200", "height": "800"},
            "requestedDelta": {"x": "8", "y": "4"},
            "rawPosition": {"x": "40", "y": "52"},
            "finalPosition": {"x": "40", "y": "52"},
            "correction": {"x": "0", "y": "0"},
            "bypassSnapping": True,
            "axisWinners": {"x": "raw", "y": "raw"},
            "candidates": [],
            "terminalReason": "pointerup",
        },
    }


def _ordinary_positioned_move_context_payload() -> tuple[
    PrototypeDocumentV1,
    dict[str, object],
]:
    document = _ordinary_positioned_document()
    root = document.pages[0].root
    assert isinstance(root, StackNodeV1)
    selected = root.children[0]
    position = selected.layout_item.position
    assert position is not None
    empty_grids: list[prototype_contracts.FreeformGridV1] = []
    return document, {
        "commandContractVersion": 1,
        "summary": "Move positioned child in ordinary container",
        "commands": [
            {
                "kind": "moveNode",
                "node": {"kind": "existing", "nodeId": selected.id},
                "targetParent": {"kind": "existing", "nodeId": root.id},
                "targetSlot": None,
                "targetIndex": 0,
                "targetPosition": {"x": "20", "y": "28"},
            }
        ],
        "evidence": {
            "evidenceVersion": 2,
            "kind": "freeformMove",
            "snapSolverVersion": "structured-prototype-freeform-snap/v1",
            "snapSolverSourceHash": _hash("f"),
            "documentId": document.id,
            "draftId": fixture_id("ordinary-move-context-draft"),
            "freeformId": root.id,
            "baseHeadSequenceNo": 7,
            "baseDocumentHash": document_hash(document),
            "selectedNodeIds": [selected.id],
            "grids": [],
            "gridListHash": freeform_grid_list_hash(empty_grids),
            "gridSnappingEnabled": False,
            "previewScale": "1",
            "clientThreshold": "6",
            "selectionBounds": {
                "x": position.x,
                "y": position.y,
                "width": "300",
                "height": "40",
            },
            "directSiblings": [],
            "containerSize": {"width": "1200", "height": "800"},
            "requestedDelta": {"x": "8", "y": "4"},
            "rawPosition": {"x": "20", "y": "28"},
            "finalPosition": {"x": "20", "y": "28"},
            "correction": {"x": "0", "y": "0"},
            "bypassSnapping": True,
            "axisWinners": {"x": "raw", "y": "raw"},
            "candidates": [],
            "terminalReason": "pointerup",
        },
    }


def _parse_batch(payload: dict[str, object]) -> DomainCommandBatchV1:
    return DomainCommandBatchV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _set_runtime_flow_position_batch(
    flow_node_id: str,
    *,
    x: int,
    y: int,
) -> DomainCommandBatchV1:
    return _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "调整业务流程节点位置",
            "commands": [
                {
                    "kind": "setRuntimeFlowNodePosition",
                    "flowNodeId": flow_node_id,
                    "x": x,
                    "y": y,
                }
            ],
        }
    )


def _behavior_rule_definition(
    key: str,
    *,
    primary_targets: tuple[str, ...] = ("page-detail",),
    guard_false_targets: tuple[str, ...] = (),
    node_key: str = "button-submit",
    event: str = "click",
    enabled: bool = True,
) -> dict[str, object]:
    effects: list[dict[str, object]] = [
        {"kind": "navigate", "targetPageId": fixture_id(target)} for target in primary_targets
    ]
    if not effects:
        effects.append({"kind": "notify", "level": "info", "message": "已处理"})
    return {
        "key": key,
        "enabled": enabled,
        "trigger": {
            "kind": "nodeEvent",
            "nodeId": fixture_id(node_key),
            "event": event,
        },
        "guard": (
            {"kind": "roleIs", "roleId": fixture_id("role-applicant")}
            if guard_false_targets
            else None
        ),
        "effects": effects,
        "guardFalseEffects": [
            {"kind": "navigate", "targetPageId": fixture_id(target)}
            for target in guard_false_targets
        ],
    }


def _add_behavior_rule_batch(
    key: str,
    definition: dict[str, object],
) -> DomainCommandBatchV1:
    return _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "新增行为规则",
            "commands": [
                {
                    "kind": "addBehaviorRule",
                    "newRuleKey": key,
                    "definition": definition,
                }
            ],
        }
    )


def _runtime_flow_projection_payload() -> tuple[dict[str, object], dict[str, str]]:
    payload = procurement_document_payload()
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    variable_id = fixture_id("flow-variable")
    rule_id = fixture_id("flow-rule")
    scenario_id = fixture_id("scenario-happy-path")
    runtime["variables"] = [
        {
            "id": variable_id,
            "key": "flow-variable",
            "valueType": "string",
            "nullable": False,
            "entitySchemaId": None,
            "defaultValue": {"type": "string", "value": ""},
        }
    ]
    runtime["rules"] = [
        {
            "id": rule_id,
            "key": "flow-rule",
            "enabled": True,
            "trigger": {
                "kind": "nodeEvent",
                "nodeId": fixture_id("button-submit"),
                "event": "click",
            },
            "guard": None,
            "effects": [{"kind": "notify", "level": "success", "message": "已提交"}],
            "guardFalseEffects": [],
        }
    ]
    return payload, {
        "page": fixture_id("page-list"),
        "variable": variable_id,
        "rule": rule_id,
        "scenario": scenario_id,
    }


def _hash(character: str) -> str:
    return "sha256:" + character * 64


def _history_batch(
    *,
    batch_id: str,
    draft_id: str,
    base_sequence_no: int,
    operation_kind: Literal["forward", "undo", "redo"],
    target_batch_id: str | None,
    command_batch_hash: str,
    base_document_hash: str,
    result_document_hash: str,
) -> PrototypeCommandBatchRecord:
    return PrototypeCommandBatchRecord(
        id=batch_id,
        draft_id=draft_id,
        base_sequence_no=base_sequence_no,
        result_sequence_no=base_sequence_no + 1,
        client_request_id=fixture_id(f"history-request-{base_sequence_no}"),
        origin="user",
        operation_kind=operation_kind,
        target_batch_id=target_batch_id,
        command_contract_version=1,
        commands_json="{}",
        inverse_commands_json="{}",
        command_batch_hash=command_batch_hash,
        base_document_hash=base_document_hash,
        result_document_hash=result_document_hash,
        operation_id=fixture_id(f"history-operation-{base_sequence_no}"),
        created_at=datetime.now(UTC),
    )


def _table_payload(payload: dict[str, object]) -> dict[str, object]:
    pages = payload["pages"]
    assert isinstance(pages, list)
    list_page = pages[0]
    assert isinstance(list_page, dict)
    root = list_page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    table = children[1]
    assert isinstance(table, dict)
    return table


def _dynamic_table_document_payload() -> tuple[dict[str, object], dict[str, object]]:
    payload = procurement_document_payload()
    table = _table_payload(payload)
    schema_id = fixture_id("table-schema")
    title_field_id = fixture_id("table-schema-title")
    status_field_id = fixture_id("table-schema-status")
    other_field_id = fixture_id("other-schema-field")
    table["columns"] = [
        {"key": "title", "label": "标题", "fieldId": title_field_id},
        {"key": "status", "label": "状态", "fieldId": status_field_id},
    ]
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["entitySchemas"] = [
        {
            "id": schema_id,
            "key": "table-record",
            "fields": [
                {
                    "id": title_field_id,
                    "key": "title",
                    "valueType": "string",
                    "nullable": False,
                },
                {
                    "id": status_field_id,
                    "key": "status",
                    "valueType": "enum",
                    "nullable": False,
                },
            ],
        },
        {
            "id": fixture_id("other-schema"),
            "key": "other-record",
            "fields": [
                {
                    "id": other_field_id,
                    "key": "other",
                    "valueType": "string",
                    "nullable": False,
                }
            ],
        },
    ]
    runtime["viewBindings"] = [
        {
            "id": fixture_id("table-view-binding"),
            "nodeId": fixture_id("table-list"),
            "target": "tableRows",
            "schemaId": schema_id,
            "sortFieldId": title_field_id,
            "sortDirection": "asc",
        }
    ]
    scenarios = runtime["scenarios"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    scenario["entityFixtures"] = [
        {
            "schemaId": schema_id,
            "entities": [
                {
                    "id": fixture_id("table-entity-open"),
                    "schemaId": schema_id,
                    "fields": [
                        {
                            "fieldId": title_field_id,
                            "value": {"type": "string", "value": "办公电脑采购"},
                        },
                        {
                            "fieldId": status_field_id,
                            "value": {"type": "enum", "value": "pending"},
                        },
                    ],
                },
                {
                    "id": fixture_id("table-entity-approved"),
                    "schemaId": schema_id,
                    "fields": [
                        {
                            "fieldId": title_field_id,
                            "value": {"type": "string", "value": "会议室设备"},
                        },
                        {
                            "fieldId": status_field_id,
                            "value": {"type": "enum", "value": "approved"},
                        },
                    ],
                },
            ],
        }
    ]
    return payload, table


def _rule_reference_document(node_key: str) -> PrototypeDocumentV1:
    payload = procurement_document_payload()
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["rules"] = [
        {
            "id": fixture_id("move-rule-only"),
            "key": "move-rule-only",
            "enabled": True,
            "trigger": {
                "kind": "nodeEvent",
                "nodeId": fixture_id(node_key),
                "event": "click",
            },
            "guard": None,
            "effects": [{"kind": "notify", "level": "success", "message": "已触发"}],
            "guardFalseEffects": [],
        }
    ]
    return PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _flow_reference_document(node_key: str) -> PrototypeDocumentV1:
    payload = procurement_document_payload()
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    rule_id = fixture_id("flow-only-rule")
    runtime["rules"] = [
        {
            "id": rule_id,
            "key": "flow-only-rule",
            "enabled": True,
            "trigger": {
                "kind": "nodeEvent",
                "nodeId": fixture_id(node_key),
                "event": "submit",
            },
            "guard": None,
            "effects": [{"kind": "navigate", "targetPageId": fixture_id("page-detail")}],
            "guardFalseEffects": [],
        }
    ]
    payload["flows"] = [
        {
            "id": fixture_id("flow-only-reference"),
            "key": "flow-only-reference",
            "ruleId": rule_id,
            "fromNodeId": fixture_id(node_key),
            "toPageId": fixture_id("page-detail"),
        }
    ]
    return PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _document_with_grid() -> PrototypeDocumentV1:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    detail_page = pages[2]
    assert isinstance(detail_page, dict)
    root = detail_page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    children.append(
        {
            "id": fixture_id("layout-grid"),
            "name": "布局网格",
            "visibility": "visible",
            "layoutItem": _layout(),
            "responsive": [],
            "type": "Grid",
            "columns": 1,
            "gap": 12,
            "padding": {"top": 4, "right": 4, "bottom": 4, "left": 4},
            "columnOverrides": [{"minWidth": 768, "columns": 2}],
            "children": [],
        }
    )
    return PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def test_document_boundary_rejects_unknown_and_snake_case_fields() -> None:
    unknown = procurement_document_payload()
    unknown["unexpected"] = True
    with pytest.raises(ValidationError):
        PrototypeDocumentV1.model_validate(unknown, strict=True, by_alias=True, by_name=False)

    snake_case = procurement_document_payload()
    snake_case["schema_version"] = snake_case.pop("schemaVersion")
    with pytest.raises(ValidationError):
        PrototypeDocumentV1.model_validate(
            snake_case,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_document_shell_requires_existing_color_tokens_and_exact_variant_fields() -> None:
    missing_token = procurement_document_payload()
    settings = missing_token["settings"]
    assert isinstance(settings, dict)
    shell = settings["shell"]
    assert isinstance(shell, dict)
    shell["accentColorTokenKey"] = "missing"
    with pytest.raises(ValidationError, match="unknown color token"):
        PrototypeDocumentV1.model_validate(
            missing_token,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    invalid_topbar = procurement_document_payload()
    settings = invalid_topbar["settings"]
    assert isinstance(settings, dict)
    shell = settings["shell"]
    assert isinstance(shell, dict)
    shell["kind"] = "topbar"
    shell.pop("navigationWidth")
    shell.pop("expandedMinWidth")
    shell["navigationWidth"] = 240
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PrototypeDocumentV1.model_validate(
            invalid_topbar,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_grid_is_a_recursive_command_container_and_inverse_restores_hash() -> None:
    document = procurement_document()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "添加响应式指标网格",
            "commands": [
                {
                    "kind": "insertNode",
                    "parent": {"kind": "existing", "nodeId": fixture_id("root-detail")},
                    "slot": None,
                    "index": 1,
                    "node": {
                        "newNodeKey": "metric-grid",
                        "type": "Grid",
                        "name": "指标网格",
                        "visibility": "visible",
                        "layoutItem": _layout(),
                        "responsive": [],
                        "columns": 1,
                        "gap": 16,
                        "padding": {"top": 8, "right": 8, "bottom": 8, "left": 8},
                        "columnOverrides": [
                            {"minWidth": 768, "columns": 2},
                            {"minWidth": 1200, "columns": 4},
                        ],
                        "children": [],
                    },
                },
                {
                    "kind": "insertNode",
                    "parent": {"kind": "new", "newNodeKey": "metric-grid"},
                    "slot": None,
                    "index": 0,
                    "node": {
                        "newNodeKey": "metric-value",
                        "type": "Text",
                        "name": "指标值",
                        "visibility": "visible",
                        "layoutItem": _layout(),
                        "responsive": [],
                        "content": "2846",
                        "semantic": "body",
                        "tone": "default",
                    },
                },
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("grid-draft"),
        client_request_id=fixture_id("grid-request"),
    )

    root = result.document.pages[2].root
    assert isinstance(root, StackNodeV1)
    grid = root.children[1]
    assert isinstance(grid, GridNodeV1)
    assert grid.children[0].name == "指标值"
    assert [(item.min_width, item.columns) for item in grid.column_overrides] == [
        (768, 2),
        (1200, 4),
    ]
    restored = apply_inverse_commands(result.document, result.inverse_commands)
    assert document_hash(restored) == document_hash(document)


def test_grid_refuses_duplicate_or_descending_breakpoints() -> None:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    detail_page = pages[2]
    assert isinstance(detail_page, dict)
    root = detail_page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    children.append(
        {
            "id": fixture_id("invalid-grid"),
            "name": "无效网格",
            "visibility": "visible",
            "layoutItem": _layout(),
            "responsive": [],
            "type": "Grid",
            "columns": 1,
            "gap": 16,
            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "columnOverrides": [
                {"minWidth": 1024, "columns": 4},
                {"minWidth": 768, "columns": 2},
            ],
            "children": [],
        }
    )

    with pytest.raises(ValidationError, match="strictly increasing"):
        PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_container_and_responsive_layout_updates_round_trip_exactly() -> None:
    document = _document_with_grid()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "调整容器与响应式布局",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": fixture_id("root-list")},
                    "update": {
                        "kind": "stackLayout",
                        "direction": "row",
                        "gap": 20,
                        "align": "center",
                        "justify": "between",
                        "padding": {"top": 8, "right": 12, "bottom": 16, "left": 20},
                    },
                },
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": fixture_id("layout-grid")},
                    "update": {
                        "kind": "gridLayout",
                        "columns": 2,
                        "gap": 24,
                        "padding": {"top": 6, "right": 8, "bottom": 10, "left": 12},
                        "columnOverrides": [
                            {"minWidth": 768, "columns": 3},
                            {"minWidth": 1200, "columns": 4},
                        ],
                    },
                },
                {
                    "kind": "setNodeProperty",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("form-node-create"),
                    },
                    "update": {
                        "kind": "formLayout",
                        "gap": 18,
                        "padding": {"top": 10, "right": 12, "bottom": 14, "left": 16},
                    },
                },
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": fixture_id("title-detail")},
                    "update": {
                        "kind": "responsiveLayout",
                        "responsive": [
                            {
                                "breakpoint": "sm",
                                "layoutItem": {"width": {"unit": "percent", "value": "100"}},
                            },
                            {"breakpoint": "md", "layoutItem": {"grow": 1}},
                            {
                                "breakpoint": "lg",
                                "layoutItem": {"maxWidth": {"unit": "px", "value": "960"}},
                            },
                        ],
                    },
                },
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("layout-update-draft"),
        client_request_id=fixture_id("layout-update-request"),
    )

    list_root = result.document.pages[0].root
    assert isinstance(list_root, StackNodeV1)
    assert (list_root.direction, list_root.gap, list_root.align, list_root.justify) == (
        "row",
        20,
        "center",
        "between",
    )
    create_root = result.document.pages[1].root
    assert isinstance(create_root, StackNodeV1)
    form = create_root.children[0]
    assert isinstance(form, FormNodeV1)
    assert form.gap == 18
    detail_root = result.document.pages[2].root
    assert isinstance(detail_root, StackNodeV1)
    title = detail_root.children[0]
    assert [override.breakpoint for override in title.responsive] == ["sm", "md", "lg"]
    grid = detail_root.children[1]
    assert isinstance(grid, GridNodeV1)
    assert (grid.columns, grid.gap) == (2, 24)
    assert [(item.min_width, item.columns) for item in grid.column_overrides] == [
        (768, 3),
        (1200, 4),
    ]
    restored = apply_inverse_commands(result.document, result.inverse_commands)
    assert document_hash(restored) == document_hash(document)


@pytest.mark.parametrize(
    ("node_key", "update"),
    [
        (
            "title-list",
            {
                "kind": "stackLayout",
                "direction": "column",
                "gap": 12,
                "align": "stretch",
                "justify": "start",
                "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            },
        ),
        (
            "root-list",
            {
                "kind": "gridLayout",
                "columns": 2,
                "gap": 12,
                "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                "columnOverrides": [],
            },
        ),
        (
            "layout-grid",
            {
                "kind": "formLayout",
                "gap": 12,
                "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            },
        ),
    ],
)
def test_container_layout_updates_refuse_wrong_node_types(
    node_key: str,
    update: dict[str, object],
) -> None:
    document = _document_with_grid()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "错误容器布局类型",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": fixture_id(node_key)},
                    "update": update,
                }
            ],
        }
    )

    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id(f"wrong-layout-{node_key}"),
            client_request_id=fixture_id(f"wrong-layout-request-{node_key}"),
        )

    assert error.value.code == "command_property_invalid"
    assert document_hash(document) == document_hash(_document_with_grid())


@pytest.mark.parametrize(
    "update",
    [
        {
            "kind": "stackLayout",
            "direction": "column",
            "gap": 129,
            "align": "stretch",
            "justify": "start",
            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
        },
        {
            "kind": "gridLayout",
            "columns": 13,
            "gap": 12,
            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "columnOverrides": [],
        },
        {
            "kind": "gridLayout",
            "columns": 2,
            "gap": 12,
            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "columnOverrides": [
                {"minWidth": 1024, "columns": 4},
                {"minWidth": 768, "columns": 2},
            ],
        },
        {
            "kind": "formLayout",
            "gap": 12,
            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 257},
        },
    ],
)
def test_container_layout_updates_enforce_bounds(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "越界容器布局",
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": fixture_id("root-list")},
                        "update": update,
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    ("responsive", "message"),
    [
        (
            [
                {"breakpoint": "md", "layoutItem": {"grow": 1}},
                {"breakpoint": "sm", "layoutItem": {"grow": 2}},
            ],
            "canonical sm, md, lg order",
        ),
        (
            [
                {"breakpoint": "sm", "layoutItem": {"grow": 1}},
                {"breakpoint": "sm", "layoutItem": {"grow": 2}},
            ],
            "duplicate responsive breakpoint",
        ),
    ],
)
def test_responsive_layout_update_refuses_noncanonical_breakpoints(
    responsive: list[dict[str, object]],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "非法响应式布局",
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                        "update": {"kind": "responsiveLayout", "responsive": responsive},
                    }
                ],
            }
        )


def test_document_refuses_out_of_order_responsive_breakpoints() -> None:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    list_page = pages[0]
    assert isinstance(list_page, dict)
    root = list_page["root"]
    assert isinstance(root, dict)
    root["responsive"] = [
        {"breakpoint": "lg", "layoutItem": {"grow": 1}},
        {"breakpoint": "md", "layoutItem": {"grow": 2}},
    ]

    with pytest.raises(ValidationError, match="canonical sm, md, lg order"):
        PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_command_execution_is_deterministic_and_inverse_restores_hash() -> None:
    document = procurement_document()
    base_hash = document_hash(document)
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "新增说明并调整文案和页面顺序",
            "commands": [
                {
                    "kind": "insertNode",
                    "parent": {"kind": "existing", "nodeId": fixture_id("root-detail")},
                    "slot": None,
                    "index": 1,
                    "node": {
                        "newNodeKey": "approval-note",
                        "type": "Text",
                        "name": "审批说明",
                        "visibility": "visible",
                        "layoutItem": _layout(),
                        "responsive": [],
                        "content": "等待主管审批",
                        "semantic": "body",
                        "tone": "muted",
                    },
                },
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "new", "newNodeKey": "approval-note"},
                    "update": {"kind": "textContent", "content": "主管审批通过后自动同步"},
                },
                {
                    "kind": "reorderPage",
                    "pageId": fixture_id("page-detail"),
                    "targetIndex": 0,
                },
            ],
        }
    )

    first = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("draft"),
        client_request_id=fixture_id("request-1"),
    )
    second = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("draft"),
        client_request_id=fixture_id("request-1"),
    )

    assert first.allocated_entity_ids == second.allocated_entity_ids
    assert first.result_document_hash == second.result_document_hash
    assert first.document.pages[0].id == fixture_id("page-detail")
    assert (
        document_hash(apply_inverse_commands(first.document, first.inverse_commands)) == base_hash
    )


def test_forward_execution_refuses_an_inverse_that_does_not_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = procurement_document()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "修改详情标题",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": fixture_id("title-detail")},
                    "update": {"kind": "textContent", "content": "已修改"},
                }
            ],
        }
    )

    def leave_result_unchanged(
        result_document: PrototypeDocumentV1,
        inverse_batch: object,
    ) -> PrototypeDocumentV1:
        del inverse_batch
        return result_document

    monkeypatch.setattr(
        prototype_contracts,
        "apply_inverse_commands",
        leave_result_unchanged,
    )
    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id("round-trip-draft"),
            client_request_id=fixture_id("round-trip-request"),
        )

    assert error.value.code == "inverse_round_trip_mismatch"


def test_remove_and_move_inverse_restore_the_exact_document() -> None:
    document = procurement_document()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "移动标题并删除详情标题",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                    "targetParent": {"kind": "existing", "nodeId": fixture_id("root-list")},
                    "targetSlot": None,
                    "targetIndex": 1,
                },
                {"kind": "removeNode", "nodeId": fixture_id("title-detail")},
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("draft"),
        client_request_id=fixture_id("request-2"),
    )

    assert document_hash(
        apply_inverse_commands(result.document, result.inverse_commands)
    ) == document_hash(document)


def test_move_node_with_runtime_view_binding_validates_only_the_final_document() -> None:
    payload, _ = _dynamic_table_document_payload()
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "移动绑定表格",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {"kind": "existing", "nodeId": fixture_id("table-list")},
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-list"),
                    },
                    "targetSlot": None,
                    "targetIndex": 0,
                }
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("move-bound-table-draft"),
        client_request_id=fixture_id("move-bound-table-request"),
    )

    root = result.document.pages[0].root
    assert isinstance(root, StackNodeV1)
    assert root.children[0].id == fixture_id("table-list")
    assert document_hash(apply_inverse_commands(result.document, result.inverse_commands)) == (
        document_hash(document)
    )


def test_move_node_with_runtime_rule_validates_only_the_final_document() -> None:
    document = _rule_reference_document("button-submit")
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "移动规则触发节点",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {"kind": "existing", "nodeId": fixture_id("button-submit")},
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-create"),
                    },
                    "targetSlot": None,
                    "targetIndex": 1,
                }
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("move-rule-node-draft"),
        client_request_id=fixture_id("move-rule-node-request"),
    )

    root = result.document.pages[1].root
    assert isinstance(root, StackNodeV1)
    assert root.children[1].id == fixture_id("button-submit")
    assert document_hash(apply_inverse_commands(result.document, result.inverse_commands)) == (
        document_hash(document)
    )


def test_move_node_with_flow_reference_validates_only_the_final_document() -> None:
    document = _flow_reference_document("button-submit")
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "移动流程来源节点",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {"kind": "existing", "nodeId": fixture_id("button-submit")},
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("form-node-create"),
                    },
                    "targetSlot": None,
                    "targetIndex": 0,
                }
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("move-flow-node-draft"),
        client_request_id=fixture_id("move-flow-node-request"),
    )

    root = result.document.pages[1].root
    assert isinstance(root, StackNodeV1)
    form = root.children[0]
    assert isinstance(form, FormNodeV1)
    assert form.children[0].id == fixture_id("button-submit")
    assert document_hash(apply_inverse_commands(result.document, result.inverse_commands)) == (
        document_hash(document)
    )


def test_remove_refuses_node_with_runtime_view_binding() -> None:
    payload, _ = _dynamic_table_document_payload()
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    base_hash = document_hash(document)
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "删除仍被引用的节点",
            "commands": [{"kind": "removeNode", "nodeId": fixture_id("table-list")}],
        }
    )

    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id("referenced-remove-draft"),
            client_request_id=fixture_id("referenced-table-remove"),
        )

    assert error.value.code == "command_target_in_use"
    assert document_hash(document) == base_hash


def test_remove_refuses_node_with_flow_only_reference() -> None:
    document = _flow_reference_document("button-submit")
    base_hash = document_hash(document)
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "删除仅被流程引用的节点",
            "commands": [{"kind": "removeNode", "nodeId": fixture_id("button-submit")}],
        }
    )

    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id("flow-only-remove-draft"),
            client_request_id=fixture_id("flow-only-remove-request"),
        )

    assert error.value.code == "command_target_in_use"
    assert document_hash(document) == base_hash


@pytest.mark.parametrize("node_key", ["button-submit", "form-node-create"])
def test_remove_refuses_runtime_rule_flow_node_or_ancestor(node_key: str) -> None:
    payload = procurement_document_payload()
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    rule_id = fixture_id("submit-rule")
    runtime["rules"] = [
        {
            "id": rule_id,
            "key": "submit-rule",
            "enabled": True,
            "trigger": {
                "kind": "nodeEvent",
                "nodeId": fixture_id("button-submit"),
                "event": "submit",
            },
            "guard": None,
            "effects": [{"kind": "navigate", "targetPageId": fixture_id("page-detail")}],
            "guardFalseEffects": [],
        }
    ]
    payload["flows"] = [
        {
            "id": fixture_id("submit-flow"),
            "key": "submit-flow",
            "ruleId": rule_id,
            "fromNodeId": fixture_id("button-submit"),
            "toPageId": fixture_id("page-detail"),
        }
    ]
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    base_hash = document_hash(document)
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "删除仍被行为引用的节点",
            "commands": [{"kind": "removeNode", "nodeId": fixture_id(node_key)}],
        }
    )

    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id("referenced-rule-remove-draft"),
            client_request_id=fixture_id(f"referenced-rule-remove-{node_key}"),
        )

    assert error.value.code == "command_target_in_use"
    assert document_hash(document) == base_hash


def test_move_into_own_subtree_is_refused() -> None:
    document = procurement_document()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "非法移动",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {"kind": "existing", "nodeId": fixture_id("form-node-create")},
                    "targetParent": {"kind": "existing", "nodeId": fixture_id("form-node-create")},
                    "targetSlot": None,
                    "targetIndex": 0,
                }
            ],
        }
    )

    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id("draft"),
            client_request_id=fixture_id("request-3"),
        )

    assert error.value.code == "command_target_invalid"


def test_page_and_navigation_reorder_apply_atomically_and_inverse_restore_hash() -> None:
    document = procurement_document()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "同步调整页面和菜单顺序",
            "commands": [
                {
                    "kind": "reorderPage",
                    "pageId": fixture_id("page-create"),
                    "targetIndex": 0,
                },
                {
                    "kind": "reorderNavigationItem",
                    "itemId": fixture_id("nav-create"),
                    "targetIndex": 0,
                },
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("page-navigation-reorder-draft"),
        client_request_id=fixture_id("page-navigation-reorder-request"),
    )

    assert result.document.pages[0].id == fixture_id("page-create")
    assert result.document.navigation.items[0].id == fixture_id("nav-create")
    assert [command.kind for command in result.inverse_commands.commands] == [
        "reorderNavigationItem",
        "reorderPage",
    ]
    assert set(result.affected_entity_ids) == {
        fixture_id("page-create"),
        fixture_id("nav-create"),
    }
    restored = apply_inverse_commands(result.document, result.inverse_commands)
    assert document_hash(restored) == document_hash(document)


@pytest.mark.parametrize(
    ("item_id", "target_index", "code"),
    [
        (fixture_id("missing-navigation-item"), 0, "command_target_missing"),
        (fixture_id("nav-create"), 2, "command_index_invalid"),
    ],
)
def test_navigation_reorder_refuses_missing_item_or_invalid_index(
    item_id: str,
    target_index: int,
    code: str,
) -> None:
    document = procurement_document()
    base_hash = document_hash(document)
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "拒绝非法菜单顺序",
            "commands": [
                {
                    "kind": "reorderPage",
                    "pageId": fixture_id("page-create"),
                    "targetIndex": 0,
                },
                {
                    "kind": "reorderNavigationItem",
                    "itemId": item_id,
                    "targetIndex": target_index,
                },
            ],
        }
    )

    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id(f"invalid-navigation-reorder-{code}"),
            client_request_id=fixture_id(f"invalid-navigation-reorder-request-{code}"),
        )

    assert error.value.code == code
    assert document_hash(document) == base_hash


def test_persisted_json_parsers_require_canonical_contract_keys() -> None:
    document = procurement_document()
    document_json = canonical_json_bytes(document.model_dump(mode="json", by_alias=True))
    parsed_document = parse_prototype_document_json(document_json)
    assert document_hash(parsed_document) == document_hash(document)

    batch_payload = {
        "commandContractVersion": 1,
        "summary": "页面排序",
        "commands": [
            {"kind": "reorderPage", "pageId": fixture_id("page-detail"), "targetIndex": 0}
        ],
    }
    batch_json = canonical_json_bytes(batch_payload).decode("utf-8")
    parsed_batch = parse_command_batch_json(batch_json)
    assert command_batch_hash(parsed_batch) == command_batch_hash(_parse_batch(batch_payload))


def test_durable_command_batch_hash_covers_the_complete_envelope() -> None:
    commands = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "页面排序",
            "commands": [
                {
                    "kind": "reorderPage",
                    "pageId": fixture_id("page-detail"),
                    "targetIndex": 0,
                }
            ],
        }
    )
    inverse = InverseCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "commands": [
                {
                    "kind": "reorderPage",
                    "pageId": fixture_id("page-detail"),
                    "targetIndex": 1,
                }
            ],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )
    base_draft_id = fixture_id("hash-draft")

    def envelope_hash(
        *,
        draft_id: str = base_draft_id,
        base_sequence_no: int = 4,
        result_sequence_no: int = 5,
        origin: Literal["user", "ai", "system"] = "user",
        operation_kind: Literal["forward", "undo", "redo"] = "forward",
        target_batch_id: str | None = None,
        inverse_commands: InverseCommandBatchV1 = inverse,
    ) -> str:
        return command_batch_envelope_hash(
            draft_id=draft_id,
            base_sequence_no=base_sequence_no,
            result_sequence_no=result_sequence_no,
            origin=origin,
            operation_kind=operation_kind,
            target_batch_id=target_batch_id,
            commands=commands,
            inverse_commands=inverse_commands,
        )

    baseline = envelope_hash()
    assert envelope_hash(draft_id=fixture_id("other-hash-draft")) != baseline
    assert envelope_hash(base_sequence_no=3) != baseline
    assert envelope_hash(result_sequence_no=6) != baseline
    assert envelope_hash(origin="ai") != baseline
    assert envelope_hash(operation_kind="undo") != baseline
    assert envelope_hash(target_batch_id=fixture_id("target-batch")) != baseline

    changed_inverse = inverse.model_copy(
        update={"commands": [inverse.commands[0].model_copy(update={"target_index": 2})]}
    )
    assert envelope_hash(inverse_commands=changed_inverse) != baseline


def test_command_history_checkpoint_is_strict_canonical_and_round_trips_domain() -> None:
    payload = {
        "schemaVersion": 1,
        "draftId": fixture_id("history-checkpoint-draft"),
        "checkpointSequenceNo": 7,
        "checkpointDocumentHash": _hash("1"),
        "journalPrefixHash": _hash("2"),
        "undoStack": [
            {
                "batchId": fixture_id("history-undo-entry"),
                "envelopeHash": _hash("3"),
            }
        ],
        "redoStack": [
            {
                "batchId": fixture_id("history-redo-entry"),
                "envelopeHash": _hash("4"),
            }
        ],
    }
    checkpoint = CommandHistoryCheckpointV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )

    canonical = canonical_command_history_checkpoint_json(checkpoint)
    assert parse_command_history_checkpoint_json(canonical) == checkpoint
    domain = command_history_checkpoint_to_domain(
        checkpoint,
        snapshot_object_hash=_hash("5"),
    )
    assert domain.to_payload() == payload
    assert command_history_checkpoint_from_domain(domain) == checkpoint
    assert domain.history.undo_stack == (
        PrototypeCommandHistoryEntry(
            batch_id=fixture_id("history-undo-entry"),
            command_batch_hash=_hash("3"),
        ),
    )
    assert "document" not in canonical

    invalid = dict(payload)
    invalid["draft_id"] = invalid.pop("draftId")
    with pytest.raises(StructuredPrototypeContractError) as error:
        parse_command_history_checkpoint_json(canonical_json_bytes(invalid))
    assert error.value.code == "command_history_checkpoint_invalid"


def test_command_history_checkpoint_refuses_invalid_stack_evidence() -> None:
    duplicate_batch_id = fixture_id("duplicate-history-entry")
    payload = {
        "schemaVersion": 1,
        "draftId": fixture_id("invalid-history-checkpoint-draft"),
        "checkpointSequenceNo": 1,
        "checkpointDocumentHash": _hash("1"),
        "journalPrefixHash": _hash("2"),
        "undoStack": [{"batchId": duplicate_batch_id, "envelopeHash": _hash("3")}],
        "redoStack": [{"batchId": duplicate_batch_id, "envelopeHash": _hash("4")}],
    }

    with pytest.raises(ValidationError, match="duplicate command history batch ID"):
        CommandHistoryCheckpointV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    payload["redoStack"] = [
        {
            "batchId": fixture_id("second-history-entry"),
            "envelopeHash": _hash("4"),
        }
    ]
    with pytest.raises(ValidationError, match="stack depth exceeds"):
        CommandHistoryCheckpointV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_journal_prefix_hash_is_deterministic_and_covers_every_durable_identity() -> None:
    draft_id = fixture_id("journal-prefix-draft")
    initial = initial_journal_prefix_hash(draft_id=draft_id)
    assert initial == initial_journal_prefix_hash(draft_id=draft_id)
    assert initial != initial_journal_prefix_hash(draft_id=fixture_id("other-prefix-draft"))

    def advance(
        *,
        previous_prefix_hash: str = initial,
        batch_id: str = fixture_id("journal-prefix-batch"),
        base_sequence_no: int = 4,
        result_sequence_no: int = 5,
        command_batch_hash: str = _hash("3"),
        base_document_hash: str = _hash("4"),
        result_document_hash: str = _hash("5"),
    ) -> str:
        return advance_journal_prefix_hash(
            previous_prefix_hash=previous_prefix_hash,
            batch_id=batch_id,
            base_sequence_no=base_sequence_no,
            result_sequence_no=result_sequence_no,
            command_batch_hash=command_batch_hash,
            base_document_hash=base_document_hash,
            result_document_hash=result_document_hash,
        )

    baseline = advance()
    assert baseline == advance()
    assert advance(previous_prefix_hash=_hash("6")) != baseline
    assert advance(batch_id=fixture_id("other-prefix-batch")) != baseline
    assert advance(base_sequence_no=8, result_sequence_no=9) != baseline
    assert advance(command_batch_hash=_hash("7")) != baseline
    assert advance(base_document_hash=_hash("8")) != baseline
    assert advance(result_document_hash=_hash("9")) != baseline

    with pytest.raises(StructuredPrototypeContractError) as error:
        advance_journal_prefix_hash(
            previous_prefix_hash=initial,
            batch_id=fixture_id("invalid-prefix-sequence"),
            base_sequence_no=4,
            result_sequence_no=6,
            command_batch_hash=_hash("3"),
            base_document_hash=_hash("4"),
            result_document_hash=_hash("5"),
        )
    assert error.value.code == "journal_prefix_invalid"


def test_command_history_can_fold_a_bounded_tail_from_checkpoint_entries() -> None:
    draft_id = fixture_id("bounded-history-draft")
    checkpoint_entry = PrototypeCommandHistoryEntry(
        batch_id=fixture_id("checkpoint-history-forward"),
        command_batch_hash=_hash("1"),
    )
    checkpoint_history = PrototypeCommandHistory(
        undo_stack=(checkpoint_entry,),
        redo_stack=(),
    )
    forward = _history_batch(
        batch_id=fixture_id("tail-forward"),
        draft_id=draft_id,
        base_sequence_no=10,
        operation_kind="forward",
        target_batch_id=None,
        command_batch_hash=_hash("2"),
        base_document_hash=_hash("3"),
        result_document_hash=_hash("4"),
    )
    undo = _history_batch(
        batch_id=fixture_id("tail-undo"),
        draft_id=draft_id,
        base_sequence_no=11,
        operation_kind="undo",
        target_batch_id=forward.id,
        command_batch_hash=_hash("5"),
        base_document_hash=forward.result_document_hash,
        result_document_hash=_hash("6"),
    )

    history = fold_prototype_command_history(
        (forward, undo),
        initial_history=checkpoint_history,
        expected_base_sequence_no=10,
        expected_base_document_hash=forward.base_document_hash,
    )

    assert history.undo_stack == (checkpoint_entry,)
    assert history.redo_stack == (
        PrototypeCommandHistoryEntry(
            batch_id=undo.id,
            command_batch_hash=undo.command_batch_hash,
        ),
    )


def test_runtime_reference_and_value_type_errors_fail_before_persistence() -> None:
    wrong_role = procurement_document_payload()
    runtime = wrong_role["runtime"]
    assert isinstance(runtime, dict)
    scenarios = runtime["scenarios"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    scenario["actorRoleId"] = fixture_id("unknown-role")
    with pytest.raises(ValidationError):
        PrototypeDocumentV1.model_validate(
            wrong_role,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    wrong_default = procurement_document_payload()
    runtime = wrong_default["runtime"]
    assert isinstance(runtime, dict)
    runtime["variables"] = [
        {
            "id": fixture_id("invalid-variable"),
            "key": "invalid-variable",
            "valueType": "integer",
            "nullable": False,
            "entitySchemaId": None,
            "defaultValue": {"type": "string", "value": "not-an-integer"},
        }
    ]
    with pytest.raises(ValidationError):
        PrototypeDocumentV1.model_validate(
            wrong_default,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_table_column_fields_are_optional_only_without_a_runtime_rows_binding() -> None:
    static_payload = procurement_document_payload()
    static_table = _table_payload(static_payload)
    static_columns = static_table["columns"]
    assert isinstance(static_columns, list)
    for column in static_columns:
        assert isinstance(column, dict)
        column["fieldId"] = None
    PrototypeDocumentV1.model_validate(
        static_payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )

    dynamic_payload, _ = _dynamic_table_document_payload()
    PrototypeDocumentV1.model_validate(
        dynamic_payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )

    missing_field_payload, missing_field_table = _dynamic_table_document_payload()
    missing_columns = missing_field_table["columns"]
    assert isinstance(missing_columns, list)
    missing_column = missing_columns[0]
    assert isinstance(missing_column, dict)
    missing_column["fieldId"] = None
    with pytest.raises(ValidationError, match="requires a schema field"):
        PrototypeDocumentV1.model_validate(
            missing_field_payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    wrong_schema_payload, wrong_schema_table = _dynamic_table_document_payload()
    wrong_columns = wrong_schema_table["columns"]
    assert isinstance(wrong_columns, list)
    wrong_column = wrong_columns[0]
    assert isinstance(wrong_column, dict)
    wrong_column["fieldId"] = fixture_id("other-schema-field")
    with pytest.raises(ValidationError, match="field is not in its binding schema"):
        PrototypeDocumentV1.model_validate(
            wrong_schema_payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_runtime_entity_field_command_updates_visible_fixture_and_inverse_restores_hash() -> None:
    payload, _ = _dynamic_table_document_payload()
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    base_hash = document_hash(document)
    entity_id = fixture_id("table-entity-open")
    title_field_id = fixture_id("table-schema-title")
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "编辑运行时表格行",
            "commands": [
                {
                    "kind": "setRuntimeEntityField",
                    "scenarioId": fixture_id("scenario-happy-path"),
                    "schemaId": fixture_id("table-schema"),
                    "entityId": entity_id,
                    "fieldId": title_field_id,
                    "value": {"type": "string", "value": "已修改的采购事项"},
                }
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("runtime-edit-draft"),
        client_request_id=fixture_id("runtime-edit-request"),
    )

    scenario = result.document.runtime.scenarios[0]
    fixture = scenario.entity_fixtures[0]
    entity = next(item for item in fixture.entities if item.id == entity_id)
    field = next(item for item in entity.fields if item.field_id == title_field_id)
    assert field.value.model_dump(mode="json", by_alias=True) == {
        "type": "string",
        "value": "已修改的采购事项",
    }
    assert (
        document_hash(apply_inverse_commands(result.document, result.inverse_commands)) == base_hash
    )


def test_runtime_entity_field_command_refuses_unknown_targets_and_wrong_value_types() -> None:
    payload, _ = _dynamic_table_document_payload()
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )

    wrong_type = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "非法运行时字段类型",
            "commands": [
                {
                    "kind": "setRuntimeEntityField",
                    "scenarioId": fixture_id("scenario-happy-path"),
                    "schemaId": fixture_id("table-schema"),
                    "entityId": fixture_id("table-entity-open"),
                    "fieldId": fixture_id("table-schema-title"),
                    "value": {"type": "integer", "value": 42},
                }
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError) as wrong_type_error:
        execute_command_batch(
            document,
            wrong_type,
            draft_id=fixture_id("runtime-edit-draft"),
            client_request_id=fixture_id("runtime-edit-wrong-type"),
        )
    assert wrong_type_error.value.code == "command_value_invalid"

    missing_entity = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "未知运行时实体",
            "commands": [
                {
                    "kind": "setRuntimeEntityField",
                    "scenarioId": fixture_id("scenario-happy-path"),
                    "schemaId": fixture_id("table-schema"),
                    "entityId": fixture_id("missing-runtime-entity"),
                    "fieldId": fixture_id("table-schema-title"),
                    "value": {"type": "string", "value": "不会写入"},
                }
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError) as missing_entity_error:
        execute_command_batch(
            document,
            missing_entity,
            draft_id=fixture_id("runtime-edit-draft"),
            client_request_id=fixture_id("runtime-edit-missing"),
        )
    assert missing_entity_error.value.code == "command_target_missing"


def test_document_refuses_duplicate_view_binding_targets_for_one_node() -> None:
    payload, _ = _dynamic_table_document_payload()
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    bindings = runtime["viewBindings"]
    assert isinstance(bindings, list)
    duplicate = deepcopy(bindings[0])
    assert isinstance(duplicate, dict)
    duplicate["id"] = fixture_id("duplicate-table-view-binding")
    duplicate["sortDirection"] = "desc"
    bindings.append(duplicate)

    with pytest.raises(ValidationError, match="duplicate runtime node view-binding target"):
        PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_table_rows_and_layout_updates_are_structurally_closed() -> None:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    list_page = pages[0]
    assert isinstance(list_page, dict)
    root = list_page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    table = children[1]
    assert isinstance(table, dict)
    table["rows"] = [
        {
            "id": fixture_id("incomplete-row"),
            "cells": [{"columnKey": "title", "value": "测试申请"}],
        }
    ]
    with pytest.raises(ValidationError):
        PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    with pytest.raises(ValidationError):
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "非法布局更新",
                "commands": [
                    {
                        "kind": "setNodeLayout",
                        "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                        "update": {"width": None},
                    }
                ],
            }
        )


def test_inverse_execution_round_trips_and_restores_the_allocated_insert_id() -> None:
    document = procurement_document()
    forward = execute_command_batch(
        document,
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "新增可撤销说明",
                "commands": [
                    {
                        "kind": "insertNode",
                        "parent": {
                            "kind": "existing",
                            "nodeId": fixture_id("root-detail"),
                        },
                        "slot": None,
                        "index": 1,
                        "node": {
                            "newNodeKey": "stable-note",
                            "type": "Text",
                            "name": "稳定说明",
                            "visibility": "visible",
                            "layoutItem": _layout(),
                            "responsive": [],
                            "content": "可撤销",
                            "semantic": "body",
                            "tone": "default",
                        },
                    }
                ],
            }
        ),
        draft_id=fixture_id("inverse-draft"),
        client_request_id=fixture_id("inverse-forward"),
    )
    inserted_id = dict(forward.allocated_entity_ids)["stable-note"]

    undone = execute_inverse_command_batch(forward.document, forward.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)

    assert undone.allocated_entity_ids == ()
    assert undone.result_document_hash == document_hash(document)
    assert redone.allocated_entity_ids == ()
    assert redone.result_document_hash == forward.result_document_hash
    assert inserted_id in redone.document.model_dump_json(by_alias=True)


def test_forward_execution_enforces_the_256_kib_request_limit() -> None:
    document = procurement_document()
    commands = [
        {
            "kind": "setNodeProperty",
            "node": {"kind": "existing", "nodeId": fixture_id("title-detail")},
            "update": {"kind": "textContent", "content": str(index) + "x" * 7_998},
        }
        for index in range(40)
    ]
    batch = DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "Oversized forward command batch",
            "commands": commands,
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )

    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id("oversized-forward-draft"),
            client_request_id=fixture_id("oversized-forward-request"),
        )

    assert error.value.code == "command_batch_too_large"


def test_optional_freeform_fields_do_not_change_legacy_canonical_payloads() -> None:
    document = procurement_document()
    document_json = canonical_json_bytes(document.model_dump(mode="json", by_alias=True))
    assert b'"position"' not in document_json

    legacy_freeform = PrototypeDocumentV1.model_validate(
        _freeform_document_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    root = legacy_freeform.pages[0].root
    assert isinstance(root, FreeformNodeV1)
    assert root.grids == []
    assert b'"grids"' not in canonical_json_bytes(
        legacy_freeform.model_dump(mode="json", by_alias=True)
    )

    legacy_move = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "旧版移动命令",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-list"),
                    },
                    "targetSlot": None,
                    "targetIndex": 1,
                }
            ],
        }
    )
    command_json = canonical_json_bytes(legacy_move.model_dump(mode="json", by_alias=True))
    assert b'"targetPosition"' not in command_json
    assert b'"evidence"' not in command_json


def test_freeform_move_evidence_round_trips_canonically_and_changes_batch_hash() -> None:
    payload = _freeform_move_evidence_batch_payload()
    batch = _parse_batch(payload)
    canonical = prototype_contracts.canonical_model_json(batch)
    parsed = parse_command_batch_json(canonical)

    assert parsed == batch
    assert parsed.model_dump(mode="json", by_alias=True) == payload
    assert prototype_contracts.canonical_model_json(parsed) == canonical
    assert '"evidence"' in canonical
    assert '"gridLineIndex":3' in canonical

    changed_payload = deepcopy(payload)
    changed_evidence = changed_payload["evidence"]
    assert isinstance(changed_evidence, dict)
    changed_evidence["gridListHash"] = _hash("c")
    changed = _parse_batch(changed_payload)
    assert command_batch_hash(changed) != command_batch_hash(batch)


@pytest.mark.parametrize(
    ("case", "match"),
    [
        ("noncanonical_decimal", "canonical signed decimal"),
        ("zero_preview_scale", "canonical positive decimal"),
        ("negative_zero", "must not be negative"),
        ("unsorted_selection", "canonical sorted order"),
        ("unsorted_siblings", "canonical nodeId order"),
        ("duplicate_sibling", "duplicate freeform move direct sibling ID"),
        ("selected_sibling_overlap", "cannot also be direct siblings"),
        ("duplicate_candidate_sort_key", "duplicate freeform move candidate sortKey"),
        ("correction_mismatch", "correction must equal"),
        ("candidate_position_mismatch", "candidate position must equal"),
        ("candidate_distance_mismatch", "candidate distance must equal"),
        ("missing_winner", "exactly one winner candidate"),
        ("raw_with_winner", "raw freeform move axis cannot have a winner"),
        ("winner_kind_mismatch", "winner kind does not match"),
        ("uncaptured_sibling", "uncaptured sibling"),
        ("uncaptured_grid", "uncaptured grid"),
        ("grid_type_mismatch", "type does not match"),
        ("grid_axis_mismatch", "axis does not match"),
        ("disabled_grid_winner", "disabled grid snapping cannot win"),
        ("invalid_alignment_target", "requires targetNodeId"),
    ],
)
def test_freeform_move_evidence_refuses_incoherent_terminal_snapshots(
    case: str,
    match: str,
) -> None:
    payload = _freeform_move_evidence_batch_payload()
    evidence = payload["evidence"]
    assert isinstance(evidence, dict)
    candidates = evidence["candidates"]
    assert isinstance(candidates, list)
    alignment = candidates[0]
    grid_candidate = candidates[2]
    assert isinstance(alignment, dict)
    assert isinstance(grid_candidate, dict)

    if case == "noncanonical_decimal":
        requested_delta = evidence["requestedDelta"]
        assert isinstance(requested_delta, dict)
        requested_delta["x"] = "01"
    elif case == "zero_preview_scale":
        evidence["previewScale"] = "0"
    elif case == "negative_zero":
        requested_delta = evidence["requestedDelta"]
        assert isinstance(requested_delta, dict)
        requested_delta["x"] = "-0"
    elif case == "unsorted_selection":
        evidence["selectedNodeIds"] = sorted(
            [fixture_id("title-list"), fixture_id("move-evidence-selection-2")],
            reverse=True,
        )
    elif case == "unsorted_siblings":
        direct_siblings = evidence["directSiblings"]
        assert isinstance(direct_siblings, list)
        direct_siblings.reverse()
    elif case == "duplicate_sibling":
        direct_siblings = evidence["directSiblings"]
        assert isinstance(direct_siblings, list)
        direct_siblings.append(deepcopy(direct_siblings[0]))
    elif case == "selected_sibling_overlap":
        evidence["selectedNodeIds"] = [fixture_id("table-list")]
        commands = payload["commands"]
        assert isinstance(commands, list)
        command = commands[0]
        assert isinstance(command, dict)
        command["node"] = {"kind": "existing", "nodeId": fixture_id("table-list")}
    elif case == "duplicate_candidate_sort_key":
        second_candidate = candidates[1]
        assert isinstance(second_candidate, dict)
        second_candidate["sortKey"] = alignment["sortKey"]
    elif case == "correction_mismatch":
        correction = evidence["correction"]
        assert isinstance(correction, dict)
        correction["x"] = "4"
    elif case == "candidate_position_mismatch":
        alignment["position"] = "41"
    elif case == "candidate_distance_mismatch":
        alignment["distance"] = "4"
    elif case == "missing_winner":
        alignment["outcome"] = "farther"
    elif case == "raw_with_winner":
        axis_winners = evidence["axisWinners"]
        assert isinstance(axis_winners, dict)
        axis_winners["x"] = "raw"
    elif case == "winner_kind_mismatch":
        axis_winners = evidence["axisWinners"]
        assert isinstance(axis_winners, dict)
        axis_winners["x"] = "spacing"
    elif case == "uncaptured_sibling":
        alignment["targetNodeId"] = fixture_id("uncaptured-move-evidence-sibling")
    elif case == "uncaptured_grid":
        grid_candidate["gridId"] = fixture_id("uncaptured-move-evidence-grid")
    elif case == "grid_type_mismatch":
        grid_candidate["gridType"] = "rows"
    elif case == "grid_axis_mismatch":
        grids = evidence["grids"]
        assert isinstance(grids, list)
        columns = _columns_freeform_grid("move-evidence-grid")
        grids[0] = columns
        grid_candidate["gridType"] = "columns"
    elif case == "disabled_grid_winner":
        evidence["gridSnappingEnabled"] = False
    elif case == "invalid_alignment_target":
        alignment["targetNodeId"] = None
    else:
        raise AssertionError(f"unsupported evidence case: {case}")

    with pytest.raises(ValidationError, match=match):
        _parse_batch(payload)


@pytest.mark.parametrize(
    "case",
    [
        "wrong_target",
        "wrong_node",
        "wrong_position",
        "unrelated_command",
        "missing_target_position",
    ],
)
def test_freeform_move_evidence_must_match_only_the_positioned_move_commands(case: str) -> None:
    payload = _freeform_move_evidence_batch_payload()
    commands = payload["commands"]
    assert isinstance(commands, list)
    command = commands[0]
    assert isinstance(command, dict)

    if case == "wrong_target":
        command["targetParent"] = {
            "kind": "existing",
            "nodeId": fixture_id("root-detail"),
        }
    elif case == "wrong_node":
        command["node"] = {"kind": "existing", "nodeId": fixture_id("table-list")}
    elif case == "wrong_position":
        command["targetPosition"] = {"x": "41", "y": "48"}
    elif case == "unrelated_command":
        commands.append(
            {"kind": "reorderPage", "pageId": fixture_id("page-detail"), "targetIndex": 0}
        )
    elif case == "missing_target_position":
        command.pop("targetPosition")
    else:
        raise AssertionError(f"unsupported linkage case: {case}")

    with pytest.raises(ValidationError, match="freeform move evidence"):
        _parse_batch(payload)


def test_freeform_move_evidence_requires_strict_aliases_hashes_and_json_scalars() -> None:
    snake_case = _freeform_move_evidence_batch_payload()
    snake_evidence = snake_case["evidence"]
    assert isinstance(snake_evidence, dict)
    snake_evidence["grid_list_hash"] = snake_evidence.pop("gridListHash")

    invalid_hash = _freeform_move_evidence_batch_payload()
    hash_evidence = invalid_hash["evidence"]
    assert isinstance(hash_evidence, dict)
    hash_evidence["baseDocumentHash"] = "abc"

    float_geometry = _freeform_move_evidence_batch_payload()
    float_evidence = float_geometry["evidence"]
    assert isinstance(float_evidence, dict)
    float_evidence["previewScale"] = 1.25

    for invalid in (snake_case, invalid_hash, float_geometry):
        with pytest.raises(ValidationError):
            _parse_batch(invalid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidenceVersion", 1),
        ("snapSolverVersion", "structured-prototype-freeform-snap/v2"),
        ("snapSolverSourceHash", "not-a-hash"),
    ],
)
def test_freeform_move_evidence_pins_solver_version_and_source_hash(
    field: str,
    value: object,
) -> None:
    payload = _freeform_move_evidence_batch_payload()
    evidence = payload["evidence"]
    assert isinstance(evidence, dict)
    evidence[field] = value

    with pytest.raises(ValidationError):
        _parse_batch(payload)


@pytest.mark.parametrize("case", ["candidate_count", "sort_key_length"])
def test_freeform_move_evidence_bounds_solver_diagnostics(case: str) -> None:
    payload = _freeform_move_evidence_batch_payload()
    evidence = payload["evidence"]
    assert isinstance(evidence, dict)
    candidates = evidence["candidates"]
    assert isinstance(candidates, list)
    if case == "candidate_count":
        template = candidates[1]
        assert isinstance(template, dict)
        while len(candidates) < 7:
            candidate = deepcopy(template)
            candidate["sortKey"] = f"extra-candidate-{len(candidates)}"
            candidates.append(candidate)
    else:
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        candidate["sortKey"] = "x" * 513

    with pytest.raises(ValidationError):
        _parse_batch(payload)


@pytest.mark.parametrize("group", [False, True], ids=["single", "group"])
def test_freeform_move_evidence_context_accepts_valid_rigid_moves(group: bool) -> None:
    document, payload = _freeform_move_context_payload(group=group)
    batch = _parse_batch(payload)

    validate_command_batch_evidence_context(
        document,
        batch,
        draft_id=fixture_id("move-context-draft"),
        base_head_sequence_no=3,
        base_document_hash=document_hash(document),
    )
    execution = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("move-context-draft"),
        client_request_id=fixture_id(f"move-context-{'group' if group else 'single'}"),
    )
    moved_root = execution.document.pages[0].root
    base_root = document.pages[0].root
    assert isinstance(moved_root, FreeformNodeV1)
    assert isinstance(base_root, FreeformNodeV1)
    assert [child.id for child in moved_root.children] == [child.id for child in base_root.children]


def test_positioned_move_evidence_context_accepts_ordinary_container_and_replays() -> None:
    document, payload = _ordinary_positioned_move_context_payload()
    batch = _parse_batch(payload)

    validate_command_batch_evidence_context(
        document,
        batch,
        draft_id=fixture_id("ordinary-move-context-draft"),
        base_head_sequence_no=7,
        base_document_hash=document_hash(document),
    )
    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("ordinary-move-context-draft"),
        client_request_id=fixture_id("ordinary-move-context-request"),
    )
    moved = prototype_contracts._require_node(result.document, fixture_id("title-list"))
    assert moved.layout_item.position is not None
    assert moved.layout_item.position.model_dump(mode="json") == {"x": "20", "y": "28"}
    undone = execute_inverse_command_batch(result.document, result.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert undone.result_document_hash == document_hash(document)
    assert redone.result_document_hash == result.result_document_hash


@pytest.mark.parametrize("case", ["captured_grid", "grid_snapping_enabled"])
def test_positioned_move_evidence_context_refuses_ordinary_container_grids(case: str) -> None:
    document, payload = _ordinary_positioned_move_context_payload()
    evidence = payload["evidence"]
    assert isinstance(evidence, dict)
    if case == "captured_grid":
        evidence["grids"] = [_square_freeform_grid("ordinary-invalid-grid")]
    else:
        evidence["gridSnappingEnabled"] = True
    batch = _parse_batch(payload)

    with pytest.raises(StructuredPrototypeContractError) as error:
        validate_command_batch_evidence_context(
            document,
            batch,
            draft_id=fixture_id("ordinary-move-context-draft"),
            base_head_sequence_no=7,
            base_document_hash=document_hash(document),
        )
    assert error.value.code == "command_evidence_mismatch"


@pytest.mark.parametrize(
    "case",
    [
        "document_id",
        "draft_id",
        "base_head",
        "base_hash",
        "freeform_missing",
        "freeform_wrong_type",
        "grid_hash",
        "grid_drift",
        "grid_order",
        "selected_non_child",
        "sibling_non_child",
        "sibling_position",
        "selection_origin",
        "raw_requested_relation",
        "rigid_group_target",
        "target_index",
    ],
)
def test_freeform_move_evidence_context_refuses_base_or_geometry_drift(case: str) -> None:
    group = case in {"rigid_group_target", "selection_origin"}
    document, payload = _freeform_move_context_payload(group=group)
    evidence = payload["evidence"]
    commands = payload["commands"]
    assert isinstance(evidence, dict)
    assert isinstance(commands, list)

    if case == "document_id":
        evidence["documentId"] = fixture_id("move-context-other-document")
    elif case == "draft_id":
        evidence["draftId"] = fixture_id("move-context-other-draft")
    elif case == "base_head":
        evidence["baseHeadSequenceNo"] = 4
    elif case == "base_hash":
        evidence["baseDocumentHash"] = _hash("d")
    elif case in {"freeform_missing", "freeform_wrong_type"}:
        freeform_id = (
            fixture_id("move-context-missing-freeform")
            if case == "freeform_missing"
            else fixture_id("root-detail")
        )
        evidence["freeformId"] = freeform_id
        for command in commands:
            assert isinstance(command, dict)
            command["targetParent"] = {"kind": "existing", "nodeId": freeform_id}
    elif case == "grid_hash":
        evidence["gridListHash"] = _hash("e")
    elif case in {"grid_drift", "grid_order"}:
        grids = evidence["grids"]
        assert isinstance(grids, list)
        if case == "grid_drift":
            square = grids[0]
            assert isinstance(square, dict)
            params = square["params"]
            assert isinstance(params, dict)
            params["size"] = "20"
        else:
            grids.reverse()
        drifted = _parse_batch(payload)
        assert drifted.evidence is not None
        evidence["gridListHash"] = freeform_grid_list_hash(drifted.evidence.grids)
    elif case == "selected_non_child":
        non_child_id = fixture_id("title-detail")
        evidence["selectedNodeIds"] = [non_child_id]
        command = commands[0]
        assert isinstance(command, dict)
        command["node"] = {"kind": "existing", "nodeId": non_child_id}
    elif case == "sibling_non_child":
        siblings = evidence["directSiblings"]
        assert isinstance(siblings, list)
        sibling = siblings[0]
        assert isinstance(sibling, dict)
        sibling["nodeId"] = fixture_id("title-detail")
    elif case == "sibling_position":
        siblings = evidence["directSiblings"]
        assert isinstance(siblings, list)
        sibling = siblings[0]
        assert isinstance(sibling, dict)
        sibling["x"] = "393"
    elif case == "selection_origin":
        selection_bounds = evidence["selectionBounds"]
        raw_position = evidence["rawPosition"]
        final_position = evidence["finalPosition"]
        assert isinstance(selection_bounds, dict)
        assert isinstance(raw_position, dict)
        assert isinstance(final_position, dict)
        selection_bounds["x"] = "31"
        raw_position["x"] = "39"
        final_position["x"] = "39"
    elif case == "raw_requested_relation":
        requested_delta = evidence["requestedDelta"]
        assert isinstance(requested_delta, dict)
        requested_delta["x"] = "7"
    elif case == "rigid_group_target":
        command = next(
            item
            for item in commands
            if isinstance(item, dict)
            and item["node"] == {"kind": "existing", "nodeId": fixture_id("table-list")}
        )
        target_position = command["targetPosition"]
        assert isinstance(target_position, dict)
        target_position["x"] = "401"
    elif case == "target_index":
        command = commands[0]
        assert isinstance(command, dict)
        command["targetIndex"] = 1
    else:
        raise AssertionError(f"unsupported context mismatch case: {case}")

    batch = _parse_batch(payload)
    with pytest.raises(StructuredPrototypeContractError) as error:
        validate_command_batch_evidence_context(
            document,
            batch,
            draft_id=fixture_id("move-context-draft"),
            base_head_sequence_no=3,
            base_document_hash=document_hash(document),
        )

    assert error.value.code == "command_evidence_mismatch"


def test_freeform_grid_list_hash_matches_cross_language_canonical_vector() -> None:
    document, _ = _freeform_move_context_payload()
    root = document.pages[0].root
    assert isinstance(root, FreeformNodeV1)

    assert freeform_grid_list_hash(root.grids) == (
        "sha256:cce2c7df00f69dce57ca210b1ee169d1bbe71b18b8403137d729ced4bc864f36"
    )


def test_freeform_grids_serialize_nonempty_canonical_configuration() -> None:
    payload = _freeform_document_payload()
    root = _freeform_root(payload)
    grids = [
        _square_freeform_grid("freeform-grid-square"),
        _columns_freeform_grid("freeform-grid-columns"),
        _rows_freeform_grid("freeform-grid-rows"),
    ]
    root["grids"] = grids

    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    freeform = document.pages[0].root
    assert isinstance(freeform, FreeformNodeV1)
    assert [grid.type for grid in freeform.grids] == ["square", "columns", "rows"]
    document_payload = document.model_dump(mode="json", by_alias=True)
    serialized_root = _freeform_root(document_payload)
    serialized_grids = serialized_root["grids"]
    assert isinstance(serialized_grids, list)
    assert serialized_grids == grids


def test_freeform_grids_refuse_invalid_schema_tokens_and_geometry() -> None:
    invalid_version = _freeform_document_payload()
    version_grid = _square_freeform_grid("invalid-grid-version")
    version_grid["version"] = 2
    _freeform_root(invalid_version)["grids"] = [version_grid]

    invalid_decimal = _freeform_document_payload()
    decimal_grid = _square_freeform_grid("invalid-grid-decimal")
    decimal_params = decimal_grid["params"]
    assert isinstance(decimal_params, dict)
    decimal_params["size"] = "01"
    _freeform_root(invalid_decimal)["grids"] = [decimal_grid]

    invalid_stretch = _freeform_document_payload()
    stretch_grid = _columns_freeform_grid("invalid-grid-stretch")
    stretch_params = stretch_grid["params"]
    assert isinstance(stretch_params, dict)
    stretch_params["itemSize"] = "64"
    _freeform_root(invalid_stretch)["grids"] = [stretch_grid]

    invalid_fixed_item_size = _freeform_document_payload()
    fixed_grid = _rows_freeform_grid("invalid-grid-fixed-item-size")
    fixed_params = fixed_grid["params"]
    assert isinstance(fixed_params, dict)
    fixed_params["itemSize"] = None
    _freeform_root(invalid_fixed_item_size)["grids"] = [fixed_grid]

    invalid_axis = _freeform_document_payload()
    axis_grid = _rows_freeform_grid("invalid-grid-axis")
    axis_params = axis_grid["params"]
    assert isinstance(axis_params, dict)
    axis_params["itemSize"] = "200"
    _freeform_root(invalid_axis)["grids"] = [axis_grid]

    unknown_token = _freeform_document_payload()
    token_grid = _square_freeform_grid("invalid-grid-token")
    token_params = token_grid["params"]
    assert isinstance(token_params, dict)
    token_params["colorTokenKey"] = "missing-color"
    _freeform_root(unknown_token)["grids"] = [token_grid]

    invalid_opacity = _freeform_document_payload()
    opacity_grid = _square_freeform_grid("invalid-grid-opacity")
    opacity_params = opacity_grid["params"]
    assert isinstance(opacity_params, dict)
    opacity_params["opacity"] = "1.0001"
    _freeform_root(invalid_opacity)["grids"] = [opacity_grid]

    invalid_origin = _freeform_document_payload()
    origin_grid = _square_freeform_grid("invalid-grid-origin")
    origin_grid["origin"] = {"x": "1200", "y": "0"}
    _freeform_root(invalid_origin)["grids"] = [origin_grid]

    duplicate_id = _freeform_document_payload()
    first_grid = _square_freeform_grid("duplicate-freeform-grid")
    _freeform_root(duplicate_id)["grids"] = [first_grid, deepcopy(first_grid)]

    too_many = _freeform_document_payload()
    _freeform_root(too_many)["grids"] = [
        _square_freeform_grid(f"freeform-grid-{index}") for index in range(9)
    ]

    invalid_cases = [
        (invalid_version, "version"),
        (invalid_decimal, "canonical non-negative decimal"),
        (invalid_stretch, "must be null for stretch"),
        (invalid_fixed_item_size, "itemSize is required outside stretch"),
        (invalid_axis, "exceeds its Freeform axis"),
        (unknown_token, "unknown color token key"),
        (invalid_opacity, "opacity must not exceed 1"),
        (invalid_origin, "origin must be inside"),
        (duplicate_id, "duplicate freeform grid ID"),
        (too_many, "at most 8"),
    ]
    for invalid_payload, match in invalid_cases:
        with pytest.raises(ValidationError, match=match):
            PrototypeDocumentV1.model_validate(
                invalid_payload,
                strict=True,
                by_alias=True,
                by_name=False,
            )


def test_freeform_grids_command_round_trips_through_inverse() -> None:
    document = PrototypeDocumentV1.model_validate(
        _freeform_document_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    freeform = document.pages[0].root
    assert isinstance(freeform, FreeformNodeV1)
    grids = [
        _square_freeform_grid("command-grid-square"),
        _columns_freeform_grid("command-grid-columns"),
    ]
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Configure Freeform grids",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": freeform.id},
                    "update": {"kind": "freeformGrids", "grids": grids},
                }
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("freeform-grid-draft"),
        client_request_id=fixture_id("freeform-grid-command"),
    )
    updated_root = result.document.pages[0].root
    assert isinstance(updated_root, FreeformNodeV1)
    assert [grid.id for grid in updated_root.grids] == [
        fixture_id("command-grid-square"),
        fixture_id("command-grid-columns"),
    ]
    inverse_payload = result.inverse_commands.model_dump(mode="json", by_alias=True)
    inverse_commands = inverse_payload["commands"]
    assert isinstance(inverse_commands, list)
    inverse = inverse_commands[0]
    assert isinstance(inverse, dict)
    assert inverse["kind"] == "setNodeProperty"
    assert inverse["update"] == {"kind": "freeformGrids", "grids": []}
    assert document_hash(
        apply_inverse_commands(result.document, result.inverse_commands)
    ) == document_hash(document)

    non_freeform_batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Invalid Freeform grid target",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                    "update": {"kind": "freeformGrids", "grids": grids},
                }
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            non_freeform_batch,
            draft_id=fixture_id("freeform-grid-draft"),
            client_request_id=fixture_id("freeform-grid-invalid-target"),
        )
    assert error.value.code == "command_property_invalid"


def test_freeform_shrink_then_grid_delete_validates_only_the_final_batch_document() -> None:
    payload = _freeform_document_payload()
    _freeform_root(payload)["grids"] = [_square_freeform_grid("shrink-delete-grid")]
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    freeform = document.pages[0].root
    assert isinstance(freeform, FreeformNodeV1)
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Shrink Freeform and remove its out-of-bounds grid",
            "commands": [
                {
                    "kind": "setNodeLayout",
                    "node": {"kind": "existing", "nodeId": freeform.id},
                    "update": {"width": {"unit": "px", "value": "8"}},
                },
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": freeform.id},
                    "update": {"kind": "freeformGrids", "grids": []},
                },
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("freeform-shrink-delete-draft"),
        client_request_id=fixture_id("freeform-shrink-delete-request"),
    )
    updated = result.document.pages[0].root
    assert isinstance(updated, FreeformNodeV1)
    assert updated.layout_item.width.value == "8"
    assert updated.grids == []

    undone = execute_inverse_command_batch(result.document, result.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert undone.result_document_hash == document_hash(document)
    assert redone.result_document_hash == result.result_document_hash


def test_freeform_grid_add_then_expand_validates_only_the_final_batch_document() -> None:
    document = PrototypeDocumentV1.model_validate(
        _freeform_document_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    freeform = document.pages[0].root
    assert isinstance(freeform, FreeformNodeV1)
    grid = _square_freeform_grid("add-expand-grid")
    grid["origin"] = {"x": "1300", "y": "0"}
    incomplete_batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Reject a grid that remains out of bounds",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": freeform.id},
                    "update": {"kind": "freeformGrids", "grids": [grid]},
                }
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            incomplete_batch,
            draft_id=fixture_id("freeform-incomplete-add-draft"),
            client_request_id=fixture_id("freeform-incomplete-add-request"),
        )
    assert error.value.code == "command_result_invalid"

    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Add an out-of-bounds grid and expand its Freeform",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {"kind": "existing", "nodeId": freeform.id},
                    "update": {"kind": "freeformGrids", "grids": [grid]},
                },
                {
                    "kind": "setNodeLayout",
                    "node": {"kind": "existing", "nodeId": freeform.id},
                    "update": {"width": {"unit": "px", "value": "1400"}},
                },
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("freeform-add-expand-draft"),
        client_request_id=fixture_id("freeform-add-expand-request"),
    )
    updated = result.document.pages[0].root
    assert isinstance(updated, FreeformNodeV1)
    assert updated.layout_item.width.value == "1400"
    assert [item.id for item in updated.grids] == [fixture_id("add-expand-grid")]

    undone = execute_inverse_command_batch(result.document, result.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert undone.result_document_hash == document_hash(document)
    assert redone.result_document_hash == result.result_document_hash


@pytest.mark.parametrize("coordinate", ["-1", "01", "1.00000", "4096.0001"])
def test_freeform_position_requires_bounded_canonical_coordinates(coordinate: str) -> None:
    payload = _freeform_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    page = pages[0]
    assert isinstance(page, dict)
    root = page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    child = children[0]
    assert isinstance(child, dict)
    layout_item = child["layoutItem"]
    assert isinstance(layout_item, dict)
    layout_item["position"] = {"x": coordinate, "y": "0"}

    with pytest.raises(ValidationError, match="freeform position"):
        PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_freeform_tree_contract_enforces_size_root_and_direct_child_positions() -> None:
    valid_payload = _freeform_document_payload()
    document = PrototypeDocumentV1.model_validate(
        valid_payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    assert isinstance(document.pages[0].root, FreeformNodeV1)

    zero_width = _freeform_document_payload()
    zero_pages = zero_width["pages"]
    assert isinstance(zero_pages, list)
    zero_page = zero_pages[0]
    assert isinstance(zero_page, dict)
    zero_root = zero_page["root"]
    assert isinstance(zero_root, dict)
    zero_layout = zero_root["layoutItem"]
    assert isinstance(zero_layout, dict)
    zero_layout["width"] = {"unit": "px", "value": "0"}
    with pytest.raises(ValidationError, match="non-zero pixel length"):
        PrototypeDocumentV1.model_validate(
            zero_width,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    positioned_root = _freeform_document_payload()
    positioned_pages = positioned_root["pages"]
    assert isinstance(positioned_pages, list)
    positioned_page = positioned_pages[0]
    assert isinstance(positioned_page, dict)
    positioned_root_node = positioned_page["root"]
    assert isinstance(positioned_root_node, dict)
    positioned_layout = positioned_root_node["layoutItem"]
    assert isinstance(positioned_layout, dict)
    positioned_layout["position"] = {"x": "0", "y": "0"}
    with pytest.raises(ValidationError, match=r"root node .* cannot have"):
        PrototypeDocumentV1.model_validate(
            positioned_root,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    missing_child_position = _freeform_document_payload()
    missing_pages = missing_child_position["pages"]
    assert isinstance(missing_pages, list)
    missing_page = missing_pages[0]
    assert isinstance(missing_page, dict)
    missing_root = missing_page["root"]
    assert isinstance(missing_root, dict)
    missing_children = missing_root["children"]
    assert isinstance(missing_children, list)
    missing_child = missing_children[0]
    assert isinstance(missing_child, dict)
    missing_layout = missing_child["layoutItem"]
    assert isinstance(missing_layout, dict)
    missing_layout.pop("position")
    with pytest.raises(ValidationError, match="requires a freeform position"):
        PrototypeDocumentV1.model_validate(
            missing_child_position,
            strict=True,
            by_alias=True,
            by_name=False,
        )

    ordinary_child_position = procurement_document_payload()
    flow_pages = ordinary_child_position["pages"]
    assert isinstance(flow_pages, list)
    flow_page = flow_pages[0]
    assert isinstance(flow_page, dict)
    flow_root = flow_page["root"]
    assert isinstance(flow_root, dict)
    flow_children = flow_root["children"]
    assert isinstance(flow_children, list)
    flow_child = flow_children[0]
    assert isinstance(flow_child, dict)
    flow_layout = flow_child["layoutItem"]
    assert isinstance(flow_layout, dict)
    flow_layout["position"] = {"x": "1", "y": "2"}
    positioned_document = PrototypeDocumentV1.model_validate(
        ordinary_child_position,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    positioned_root = positioned_document.pages[0].root
    assert isinstance(positioned_root, StackNodeV1)
    assert positioned_root.children[0].layout_item.position is not None
    assert positioned_root.children[0].layout_item.position.model_dump(mode="json") == {
        "x": "1",
        "y": "2",
    }


def test_responsive_layout_override_refuses_freeform_position_even_when_null() -> None:
    with pytest.raises(ValidationError, match="cannot set freeform position"):
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "非法响应式坐标",
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {
                            "kind": "existing",
                            "nodeId": fixture_id("title-list"),
                        },
                        "update": {
                            "kind": "responsiveLayout",
                            "responsive": [
                                {
                                    "breakpoint": "sm",
                                    "layoutItem": {"position": None},
                                }
                            ],
                        },
                    }
                ],
            }
        )


def test_move_node_across_freeform_boundary_updates_position_and_inverse() -> None:
    document = PrototypeDocumentV1.model_validate(
        _freeform_document_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    base_hash = document_hash(document)
    move_to_stack = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "移出自由布局",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-detail"),
                    },
                    "targetSlot": None,
                    "targetIndex": 1,
                    "targetPosition": None,
                }
            ],
        }
    )

    moved_to_stack = execute_command_batch(
        document,
        move_to_stack,
        draft_id=fixture_id("freeform-move-draft"),
        client_request_id=fixture_id("freeform-move-to-stack"),
    )
    detail_root = next(
        page.root
        for page in moved_to_stack.document.pages
        if page.root.id == fixture_id("root-detail")
    )
    assert isinstance(detail_root, StackNodeV1)
    moved_title = detail_root.children[1]
    assert moved_title.id == fixture_id("title-list")
    assert moved_title.layout_item.position is None
    assert '"targetPosition":null' in prototype_contracts.canonical_model_json(move_to_stack)
    inverse_payload = moved_to_stack.inverse_commands.model_dump(mode="json", by_alias=True)
    inverse_commands = inverse_payload["commands"]
    assert isinstance(inverse_commands, list)
    inverse_move = inverse_commands[0]
    assert isinstance(inverse_move, dict)
    assert inverse_move["targetPosition"] == {"x": "32", "y": "48"}
    assert (
        document_hash(
            apply_inverse_commands(moved_to_stack.document, moved_to_stack.inverse_commands)
        )
        == base_hash
    )

    move_into_freeform = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "移入自由布局",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-detail"),
                    },
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-list"),
                    },
                    "targetSlot": None,
                    "targetIndex": 2,
                    "targetPosition": {"x": "720", "y": "48"},
                }
            ],
        }
    )
    moved_into_freeform = execute_command_batch(
        document,
        move_into_freeform,
        draft_id=fixture_id("freeform-move-draft"),
        client_request_id=fixture_id("freeform-move-into-canvas"),
    )
    freeform_root = moved_into_freeform.document.pages[0].root
    assert isinstance(freeform_root, FreeformNodeV1)
    assert freeform_root.children[2].layout_item.position is not None
    assert freeform_root.children[2].layout_item.position.x == "720"
    assert (
        document_hash(
            apply_inverse_commands(
                moved_into_freeform.document,
                moved_into_freeform.inverse_commands,
            )
        )
        == base_hash
    )


def test_move_node_requires_position_when_entering_freeform_from_flow() -> None:
    document = PrototypeDocumentV1.model_validate(
        _freeform_document_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    missing_position = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "缺少自由布局坐标",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-detail"),
                    },
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-list"),
                    },
                    "targetSlot": None,
                    "targetIndex": 2,
                }
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError, match="requires a target position"):
        execute_command_batch(
            document,
            missing_position,
            draft_id=fixture_id("invalid-freeform-move-draft"),
            client_request_id=fixture_id("missing-freeform-position"),
        )

    ordinary_absolute_position = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "普通容器绝对定位",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-detail"),
                    },
                    "targetSlot": None,
                    "targetIndex": 1,
                    "targetPosition": {"x": "0", "y": "0"},
                }
            ],
        }
    )
    positioned = execute_command_batch(
        document,
        ordinary_absolute_position,
        draft_id=fixture_id("ordinary-absolute-move-draft"),
        client_request_id=fixture_id("ordinary-absolute-position"),
    )
    detail_root = next(
        page.root for page in positioned.document.pages if page.root.id == fixture_id("root-detail")
    )
    assert isinstance(detail_root, StackNodeV1)
    assert detail_root.children[1].layout_item.position is not None
    assert detail_root.children[1].layout_item.position.model_dump(mode="json") == {
        "x": "0",
        "y": "0",
    }


@pytest.mark.parametrize(
    ("target_position_marker", "expected_position"),
    [
        ("omitted", {"x": "12", "y": "24"}),
        ("null", None),
        ("position", {"x": "80", "y": "96"}),
    ],
)
def test_move_node_target_position_tristate_is_canonical_and_replayable(
    target_position_marker: str,
    expected_position: dict[str, str] | None,
) -> None:
    document = _ordinary_positioned_document()
    command: dict[str, object] = {
        "kind": "moveNode",
        "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
        "targetParent": {
            "kind": "existing",
            "nodeId": fixture_id("root-detail"),
        },
        "targetSlot": None,
        "targetIndex": 1,
    }
    if target_position_marker == "null":
        command["targetPosition"] = None
    elif target_position_marker == "position":
        command["targetPosition"] = {"x": "80", "y": "96"}
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": f"Move with {target_position_marker} target position",
            "commands": [command],
        }
    )

    canonical = prototype_contracts.canonical_model_json(batch)
    if target_position_marker == "omitted":
        assert '"targetPosition"' not in canonical
    elif target_position_marker == "null":
        assert '"targetPosition":null' in canonical
    else:
        assert '"targetPosition":{"x":"80","y":"96"}' in canonical
    replay_batch = parse_command_batch_json(canonical)
    replay_command = replay_batch.commands[0]
    assert ("target_position" in replay_command.model_fields_set) is (
        target_position_marker != "omitted"
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id(f"move-tristate-{target_position_marker}-draft"),
        client_request_id=fixture_id(f"move-tristate-{target_position_marker}-request"),
    )
    moved = prototype_contracts._require_node(result.document, fixture_id("title-list"))
    actual_position = (
        moved.layout_item.position.model_dump(mode="json")
        if moved.layout_item.position is not None
        else None
    )
    assert actual_position == expected_position

    replayed = execute_command_batch(
        document,
        replay_batch,
        draft_id=fixture_id(f"move-tristate-{target_position_marker}-draft"),
        client_request_id=fixture_id(f"move-tristate-{target_position_marker}-request"),
    )
    assert replayed.result_document_hash == result.result_document_hash
    undone = execute_inverse_command_batch(result.document, result.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert undone.result_document_hash == document_hash(document)
    assert redone.result_document_hash == result.result_document_hash


def test_move_node_from_flow_to_absolute_serializes_null_inverse_for_exact_replay() -> None:
    document = procurement_document()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Move flow child into ordinary absolute placement",
            "commands": [
                {
                    "kind": "moveNode",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-list"),
                    },
                    "targetParent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-detail"),
                    },
                    "targetSlot": None,
                    "targetIndex": 1,
                    "targetPosition": {"x": "120", "y": "144"},
                }
            ],
        }
    )
    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("flow-to-absolute-draft"),
        client_request_id=fixture_id("flow-to-absolute-request"),
    )
    inverse_json = prototype_contracts.canonical_model_json(result.inverse_commands)
    assert '"targetPosition":null' in inverse_json
    parsed_inverse = prototype_contracts.parse_inverse_command_batch_json(inverse_json)
    restored = execute_inverse_command_batch(result.document, parsed_inverse)
    assert restored.result_document_hash == document_hash(document)
    redone = execute_inverse_command_batch(restored.document, restored.inverse_commands)
    assert redone.result_document_hash == result.result_document_hash


def test_set_node_layout_supports_ordinary_absolute_and_flow_with_exact_replay() -> None:
    document = procurement_document()
    set_absolute = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Set ordinary child absolute position",
            "commands": [
                {
                    "kind": "setNodeLayout",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-list"),
                    },
                    "update": {"position": {"x": "40", "y": "56"}},
                }
            ],
        }
    )
    result = execute_command_batch(
        document,
        set_absolute,
        draft_id=fixture_id("ordinary-layout-absolute-draft"),
        client_request_id=fixture_id("ordinary-layout-absolute-request"),
    )
    positioned = prototype_contracts._require_node(result.document, fixture_id("title-list"))
    assert positioned.layout_item.position is not None
    assert positioned.layout_item.position.model_dump(mode="json") == {"x": "40", "y": "56"}
    inverse_json = prototype_contracts.canonical_model_json(result.inverse_commands)
    assert '"position":null' in inverse_json

    replay_batch = parse_command_batch_json(prototype_contracts.canonical_model_json(set_absolute))
    replayed = execute_command_batch(
        document,
        replay_batch,
        draft_id=fixture_id("ordinary-layout-absolute-draft"),
        client_request_id=fixture_id("ordinary-layout-absolute-request"),
    )
    assert replayed.result_document_hash == result.result_document_hash
    undone = execute_inverse_command_batch(result.document, result.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert undone.result_document_hash == document_hash(document)
    assert redone.result_document_hash == result.result_document_hash

    clear_position = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Return ordinary child to flow",
            "commands": [
                {
                    "kind": "setNodeLayout",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-list"),
                    },
                    "update": {"position": None},
                }
            ],
        }
    )
    cleared = execute_command_batch(
        result.document,
        clear_position,
        draft_id=fixture_id("ordinary-layout-flow-draft"),
        client_request_id=fixture_id("ordinary-layout-flow-request"),
    )
    flow_node = prototype_contracts._require_node(cleared.document, fixture_id("title-list"))
    assert flow_node.layout_item.position is None
    restored = execute_inverse_command_batch(cleared.document, cleared.inverse_commands)
    assert restored.result_document_hash == result.result_document_hash


def test_set_node_layout_refuses_root_position_and_freeform_flow_child() -> None:
    root_position = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Reject positioned root",
            "commands": [
                {
                    "kind": "setNodeLayout",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-list"),
                    },
                    "update": {"position": {"x": "0", "y": "0"}},
                }
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError) as root_error:
        execute_command_batch(
            procurement_document(),
            root_position,
            draft_id=fixture_id("invalid-root-layout-draft"),
            client_request_id=fixture_id("invalid-root-layout-request"),
        )
    assert root_error.value.code == "command_result_invalid"

    freeform_document = PrototypeDocumentV1.model_validate(
        _freeform_document_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    clear_freeform_child = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Reject flow child in Freeform",
            "commands": [
                {
                    "kind": "setNodeLayout",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-list"),
                    },
                    "update": {"position": None},
                }
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError) as freeform_error:
        execute_command_batch(
            freeform_document,
            clear_freeform_child,
            draft_id=fixture_id("invalid-freeform-layout-draft"),
            client_request_id=fixture_id("invalid-freeform-layout-request"),
        )
    assert freeform_error.value.code == "command_result_invalid"


def test_set_node_layout_updates_freeform_position_and_size_atomically_with_inverse() -> None:
    document = PrototypeDocumentV1.model_validate(
        _freeform_document_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )
    base_hash = document_hash(document)
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "调整自由布局节点",
            "commands": [
                {
                    "kind": "setNodeLayout",
                    "node": {"kind": "existing", "nodeId": fixture_id("title-list")},
                    "update": {
                        "position": {"x": "96.5", "y": "120"},
                        "width": {"unit": "px", "value": "280"},
                        "height": {"unit": "px", "value": "72"},
                    },
                }
            ],
        }
    )

    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("freeform-layout-draft"),
        client_request_id=fixture_id("freeform-layout-update"),
    )
    root = result.document.pages[0].root
    assert isinstance(root, FreeformNodeV1)
    title = root.children[0]
    assert title.layout_item.position is not None
    assert title.layout_item.position.model_dump(mode="json") == {"x": "96.5", "y": "120"}
    assert title.layout_item.width.model_dump(mode="json") == {"unit": "px", "value": "280"}
    assert title.layout_item.height.model_dump(mode="json") == {"unit": "px", "value": "72"}
    inverse_payload = result.inverse_commands.model_dump(mode="json", by_alias=True)
    inverse_commands = inverse_payload["commands"]
    assert isinstance(inverse_commands, list)
    inverse_command = inverse_commands[0]
    assert isinstance(inverse_command, dict)
    inverse_update = inverse_command["update"]
    assert isinstance(inverse_update, dict)
    assert inverse_update["position"] == {"x": "32", "y": "48"}
    assert set(inverse_update) == {"position", "width", "height"}
    assert document_hash(apply_inverse_commands(result.document, result.inverse_commands)) == (
        base_hash
    )

    clear_position = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "显式清除坐标",
            "commands": [
                {
                    "kind": "setNodeLayout",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-detail"),
                    },
                    "update": {"position": None},
                }
            ],
        }
    )
    clear_json = canonical_json_bytes(clear_position.model_dump(mode="json", by_alias=True))
    assert b'"position":null' in clear_json


def test_empty_runtime_flow_layout_preserves_legacy_serialization_and_hash() -> None:
    expected_hash = "sha256:3a90cfc9a2ca952b20062b6e28b4f208dbe10d3a8d06d21815de90a99c08c062"
    missing = procurement_document()
    empty_payload = procurement_document_payload()
    runtime = empty_payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["flowLayout"] = {"nodes": []}
    explicit_empty = PrototypeDocumentV1.model_validate(
        empty_payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )

    for document in (missing, explicit_empty):
        serialized = canonical_json_bytes(document.model_dump(mode="json", by_alias=True))
        assert b'"flowLayout"' not in serialized
        assert document_hash(document) == expected_hash


def test_runtime_flow_layout_requires_unique_canonical_node_order() -> None:
    first_id, second_id = sorted([fixture_id("flow-order-first"), fixture_id("flow-order-second")])
    canonical_nodes = [
        {"nodeId": first_id, "x": 0, "y": 0},
        {"nodeId": second_id, "x": 1, "y": 1},
    ]
    layout = prototype_contracts.RuntimeFlowLayoutV1.model_validate(
        {"nodes": canonical_nodes},
        strict=True,
        by_alias=True,
        by_name=False,
    )
    assert [node.node_id for node in layout.nodes] == [first_id, second_id]

    with pytest.raises(ValidationError, match="canonical nodeId order"):
        prototype_contracts.RuntimeFlowLayoutV1.model_validate(
            {"nodes": list(reversed(canonical_nodes))},
            strict=True,
            by_alias=True,
            by_name=False,
        )

    with pytest.raises(ValidationError, match="duplicate runtime flow layout node ID"):
        prototype_contracts.RuntimeFlowLayoutV1.model_validate(
            {"nodes": [canonical_nodes[0], canonical_nodes[0]]},
            strict=True,
            by_alias=True,
            by_name=False,
        )


@pytest.mark.parametrize("coordinate", [-32_768, 32_768])
def test_runtime_flow_layout_accepts_coordinate_bounds(coordinate: int) -> None:
    position = prototype_contracts.RuntimeFlowNodePositionV1.model_validate(
        {"nodeId": fixture_id(f"flow-coordinate-{coordinate}"), "x": coordinate, "y": coordinate},
        strict=True,
        by_alias=True,
        by_name=False,
    )
    assert position.x == coordinate
    assert position.y == coordinate


@pytest.mark.parametrize("coordinate", [-32_769, 32_769, 0.0, "0", True])
def test_runtime_flow_layout_rejects_invalid_or_non_integer_coordinates(
    coordinate: object,
) -> None:
    with pytest.raises(ValidationError):
        prototype_contracts.RuntimeFlowNodePositionV1.model_validate(
            {"nodeId": fixture_id("flow-invalid-coordinate"), "x": coordinate, "y": 0},
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_runtime_flow_layout_allows_at_most_300_nodes() -> None:
    nodes = sorted(
        [
            {
                "nodeId": fixture_id(f"flow-layout-limit-{index}"),
                "x": index,
                "y": -index,
            }
            for index in range(301)
        ],
        key=lambda node: str(node["nodeId"]),
    )
    layout = prototype_contracts.RuntimeFlowLayoutV1.model_validate(
        {"nodes": nodes[:300]},
        strict=True,
        by_alias=True,
        by_name=False,
    )
    assert len(layout.nodes) == 300

    with pytest.raises(ValidationError):
        prototype_contracts.RuntimeFlowLayoutV1.model_validate(
            {"nodes": nodes},
            strict=True,
            by_alias=True,
            by_name=False,
        )


def test_runtime_flow_layout_accepts_only_projection_entity_kinds() -> None:
    payload, projection_ids = _runtime_flow_projection_payload()
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["flowLayout"] = {
        "nodes": [
            {"nodeId": node_id, "x": index, "y": -index}
            for index, node_id in enumerate(sorted(projection_ids.values()))
        ]
    }

    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    assert document.runtime.flow_layout is not None
    assert {node.node_id for node in document.runtime.flow_layout.nodes} == set(
        projection_ids.values()
    )


def test_runtime_flow_layout_rejects_non_projection_entity_ids() -> None:
    payload, _ = _dynamic_table_document_payload()
    forbidden_ids = [
        fixture_id("unknown-flow-projection"),
        fixture_id("title-list"),
        fixture_id("nav-list"),
        fixture_id("role-applicant"),
        fixture_id("form-create"),
        fixture_id("form-field-title"),
        fixture_id("table-schema"),
        fixture_id("table-schema-title"),
        fixture_id("table-view-binding"),
        fixture_id("table-entity-open"),
    ]

    for forbidden_id in forbidden_ids:
        candidate = deepcopy(payload)
        runtime = candidate["runtime"]
        assert isinstance(runtime, dict)
        runtime["flowLayout"] = {"nodes": [{"nodeId": forbidden_id, "x": 0, "y": 0}]}
        with pytest.raises(ValidationError, match="unknown projection entity"):
            PrototypeDocumentV1.model_validate(
                candidate,
                strict=True,
                by_alias=True,
                by_name=False,
            )


def test_set_runtime_flow_position_uses_flow_node_id_payload_field() -> None:
    page_id = fixture_id("page-list")
    batch = _set_runtime_flow_position_batch(page_id, x=120, y=-80)
    payload = batch.model_dump(mode="json", by_alias=True)
    commands = payload["commands"]
    assert isinstance(commands, list)
    command = commands[0]
    assert isinstance(command, dict)
    assert command["flowNodeId"] == page_id
    assert "nodeId" not in command

    with pytest.raises(ValidationError):
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "错误的字段名",
                "commands": [
                    {
                        "kind": "setRuntimeFlowNodePosition",
                        "nodeId": page_id,
                        "x": 120,
                        "y": -80,
                    }
                ],
            }
        )


def test_first_runtime_flow_position_set_undoes_to_complete_absence() -> None:
    document = procurement_document()
    base_hash = document_hash(document)
    page_id = fixture_id("page-list")
    result = execute_command_batch(
        document,
        _set_runtime_flow_position_batch(page_id, x=100, y=200),
        draft_id=fixture_id("flow-layout-first-draft"),
        client_request_id=fixture_id("flow-layout-first-request"),
    )
    assert result.document.runtime.flow_layout is not None
    inverse_payload = result.inverse_commands.model_dump(mode="json", by_alias=True)
    inverse_commands = inverse_payload["commands"]
    assert isinstance(inverse_commands, list)
    assert inverse_commands == [
        {
            "kind": "removeRuntimeFlowNodePosition",
            "flowNodeId": page_id,
        }
    ]

    restored = apply_inverse_commands(result.document, result.inverse_commands)
    restored_payload = restored.model_dump(mode="json", by_alias=True)
    restored_runtime = restored_payload["runtime"]
    assert isinstance(restored_runtime, dict)
    assert "flowLayout" not in restored_runtime
    assert document_hash(restored) == base_hash


def test_runtime_flow_position_replacement_supports_exact_undo_and_redo() -> None:
    document = procurement_document()
    page_id = fixture_id("page-create")
    first = execute_command_batch(
        document,
        _set_runtime_flow_position_batch(page_id, x=10, y=20),
        draft_id=fixture_id("flow-layout-replace-draft"),
        client_request_id=fixture_id("flow-layout-first-position"),
    )
    replaced = execute_command_batch(
        first.document,
        _set_runtime_flow_position_batch(page_id, x=-300, y=400),
        draft_id=fixture_id("flow-layout-replace-draft"),
        client_request_id=fixture_id("flow-layout-replacement"),
    )
    inverse_payload = replaced.inverse_commands.model_dump(mode="json", by_alias=True)
    inverse_commands = inverse_payload["commands"]
    assert isinstance(inverse_commands, list)
    assert inverse_commands == [
        {
            "kind": "restoreRuntimeFlowNodePosition",
            "flowNodeId": page_id,
            "x": 10,
            "y": 20,
        }
    ]
    assert document_hash(
        apply_inverse_commands(replaced.document, replaced.inverse_commands)
    ) == document_hash(first.document)

    undone = execute_inverse_command_batch(replaced.document, replaced.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert undone.allocated_entity_ids == ()
    assert undone.result_document_hash == first.result_document_hash
    assert redone.allocated_entity_ids == ()
    assert redone.result_document_hash == replaced.result_document_hash


def test_runtime_flow_position_commands_always_store_canonical_node_order() -> None:
    document = procurement_document()
    page_ids = sorted(page.id for page in document.pages)
    commands = [
        {
            "kind": "setRuntimeFlowNodePosition",
            "flowNodeId": page_id,
            "x": index,
            "y": -index,
        }
        for index, page_id in enumerate(reversed(page_ids))
    ]
    result = execute_command_batch(
        document,
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "逆序调整流程节点",
                "commands": commands,
            }
        ),
        draft_id=fixture_id("flow-layout-order-draft"),
        client_request_id=fixture_id("flow-layout-order-request"),
    )
    assert result.document.runtime.flow_layout is not None
    assert [node.node_id for node in result.document.runtime.flow_layout.nodes] == page_ids


def test_runtime_flow_position_command_rejects_non_projection_entity() -> None:
    document = procurement_document()
    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            _set_runtime_flow_position_batch(fixture_id("title-list"), x=0, y=0),
            draft_id=fixture_id("flow-layout-invalid-draft"),
            client_request_id=fixture_id("flow-layout-invalid-request"),
        )
    assert error.value.code == "command_target_missing"


def test_behavior_rule_commands_use_strict_public_definitions() -> None:
    definition = _behavior_rule_definition("submit-rule")
    payload = {
        "commandContractVersion": 1,
        "summary": "新增行为规则",
        "commands": [
            {
                "kind": "addBehaviorRule",
                "newRuleKey": "submit-rule",
                "definition": definition,
            }
        ],
    }
    invalid_payloads = []
    extra_command = deepcopy(payload)
    commands = extra_command["commands"]
    assert isinstance(commands, list)
    command = commands[0]
    assert isinstance(command, dict)
    command["unexpected"] = True
    invalid_payloads.append(extra_command)

    definition_with_id = deepcopy(payload)
    commands = definition_with_id["commands"]
    assert isinstance(commands, list)
    command = commands[0]
    assert isinstance(command, dict)
    command_definition = command["definition"]
    assert isinstance(command_definition, dict)
    command_definition["id"] = fixture_id("client-rule-id")
    invalid_payloads.append(definition_with_id)

    mismatched_key = deepcopy(payload)
    commands = mismatched_key["commands"]
    assert isinstance(commands, list)
    command = commands[0]
    assert isinstance(command, dict)
    command["newRuleKey"] = "different-rule"
    invalid_payloads.append(mismatched_key)

    for invalid in invalid_payloads:
        with pytest.raises(ValidationError):
            _parse_batch(invalid)


def test_add_behavior_rule_allocates_deterministic_rule_and_complete_flows() -> None:
    document = procurement_document()
    draft_id = fixture_id("behavior-rule-add-draft")
    request_id = fixture_id("behavior-rule-add-request")
    definition = _behavior_rule_definition(
        "submit-rule",
        primary_targets=("page-detail", "page-detail"),
        guard_false_targets=("page-list", "page-detail"),
    )
    batch = _add_behavior_rule_batch("submit-rule", definition)

    result = execute_command_batch(
        document,
        batch,
        draft_id=draft_id,
        client_request_id=request_id,
    )
    expected_rule_id = str(
        uuid5(
            prototype_contracts.PROTOTYPE_ENTITY_NAMESPACE,
            f"{draft_id}:{request_id}:rule:submit-rule",
        )
    )
    rule = result.document.runtime.rules[0]
    assert rule.id == expected_rule_id
    serialized_rule = rule.model_dump(mode="json", by_alias=True)
    serialized_rule.pop("id")
    assert serialized_rule == definition

    expected_targets = [fixture_id("page-detail"), fixture_id("page-list")]
    assert [flow.to_page_id for flow in result.document.flows] == expected_targets
    expected_flow_ids = [str(uuid5(UUID(expected_rule_id), target)) for target in expected_targets]
    assert [flow.id for flow in result.document.flows] == expected_flow_ids
    allocations = dict(result.allocated_entity_ids)
    assert allocations["submit-rule"] == expected_rule_id
    assert {allocations[flow.key] for flow in result.document.flows} == set(expected_flow_ids)
    assert set(allocations.values()) == {expected_rule_id, *expected_flow_ids}
    assert all(flow.rule_id == expected_rule_id for flow in result.document.flows)
    assert all(flow.from_node_id == fixture_id("button-submit") for flow in result.document.flows)
    assert set(expected_flow_ids) | {
        expected_rule_id,
        fixture_id("button-submit"),
        *expected_targets,
    } <= set(result.affected_entity_ids)
    assert set(allocations.values()) <= set(result.affected_entity_ids)

    repeated = execute_command_batch(
        document,
        batch,
        draft_id=draft_id,
        client_request_id=request_id,
    )
    distinct_request = execute_command_batch(
        document,
        batch,
        draft_id=draft_id,
        client_request_id=fixture_id("behavior-rule-add-other-request"),
    )
    assert repeated.result_document_hash == result.result_document_hash
    assert repeated.allocated_entity_ids == result.allocated_entity_ids
    assert distinct_request.allocated_entity_ids != result.allocated_entity_ids
    assert prototype_contracts.canonical_model_json(
        apply_inverse_commands(result.document, result.inverse_commands)
    ) == prototype_contracts.canonical_model_json(document)


def test_behavior_rule_without_navigation_creates_no_flow_or_self_edge() -> None:
    definition = _behavior_rule_definition("notify-only", primary_targets=())
    definition["guard"] = {
        "kind": "roleIs",
        "roleId": fixture_id("role-applicant"),
    }
    definition["guardFalseEffects"] = [{"kind": "notify", "level": "warning", "message": "未执行"}]
    result = execute_command_batch(
        procurement_document(),
        _add_behavior_rule_batch("notify-only", definition),
        draft_id=fixture_id("behavior-rule-no-navigation-draft"),
        client_request_id=fixture_id("behavior-rule-no-navigation-request"),
    )

    assert len(result.document.runtime.rules) == 1
    assert result.document.flows == []

    rule_id = result.document.runtime.rules[0].id
    replaced = execute_command_batch(
        result.document,
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "为无导航规则增加导航",
                "commands": [
                    {
                        "kind": "replaceBehaviorRule",
                        "ruleId": rule_id,
                        "definition": _behavior_rule_definition("notify-only"),
                    }
                ],
            }
        ),
        draft_id=fixture_id("behavior-rule-no-navigation-draft"),
        client_request_id=fixture_id("behavior-rule-add-navigation-request"),
    )
    assert [flow.to_page_id for flow in replaced.document.flows] == [fixture_id("page-detail")]
    assert replaced.document.flows[0].id == str(uuid5(UUID(rule_id), fixture_id("page-detail")))
    assert replaced.allocated_entity_ids == (
        (replaced.document.flows[0].key, replaced.document.flows[0].id),
    )
    restored = apply_inverse_commands(replaced.document, replaced.inverse_commands)
    assert prototype_contracts.canonical_model_json(restored) == (
        prototype_contracts.canonical_model_json(result.document)
    )


def test_replace_behavior_rule_synchronizes_projection_and_round_trips_exactly() -> None:
    document = procurement_document()
    added = execute_command_batch(
        document,
        _add_behavior_rule_batch(
            "submit-rule",
            _behavior_rule_definition(
                "submit-rule",
                primary_targets=("page-detail", "page-list"),
            ),
        ),
        draft_id=fixture_id("behavior-rule-replace-draft"),
        client_request_id=fixture_id("behavior-rule-replace-add"),
    )
    rule_id = added.document.runtime.rules[0].id
    old_flows = {flow.to_page_id: flow for flow in added.document.flows}
    replacement = _behavior_rule_definition(
        "renamed-rule",
        primary_targets=("page-create",),
        guard_false_targets=("page-detail",),
        event="submit",
    )
    replaced = execute_command_batch(
        added.document,
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "替换行为规则",
                "commands": [
                    {
                        "kind": "replaceBehaviorRule",
                        "ruleId": rule_id,
                        "definition": replacement,
                    }
                ],
            }
        ),
        draft_id=fixture_id("behavior-rule-replace-draft"),
        client_request_id=fixture_id("behavior-rule-replace-request"),
    )

    replaced_rule = replaced.document.runtime.rules[0]
    assert replaced_rule.id == rule_id
    serialized_rule = replaced_rule.model_dump(mode="json", by_alias=True)
    serialized_rule.pop("id")
    assert serialized_rule == replacement
    expected_targets = [fixture_id("page-create"), fixture_id("page-detail")]
    assert [flow.to_page_id for flow in replaced.document.flows] == expected_targets
    retained = next(
        flow for flow in replaced.document.flows if flow.to_page_id == fixture_id("page-detail")
    )
    assert retained.id == old_flows[fixture_id("page-detail")].id
    assert retained.key == old_flows[fixture_id("page-detail")].key
    created = next(
        flow for flow in replaced.document.flows if flow.to_page_id == fixture_id("page-create")
    )
    assert created.id == str(uuid5(UUID(rule_id), fixture_id("page-create")))
    assert replaced.allocated_entity_ids == ((created.key, created.id),)
    assert created.id in replaced.affected_entity_ids
    assert retained.id in replaced.affected_entity_ids

    restored = apply_inverse_commands(replaced.document, replaced.inverse_commands)
    assert prototype_contracts.canonical_model_json(restored) == (
        prototype_contracts.canonical_model_json(added.document)
    )
    undone = execute_inverse_command_batch(replaced.document, replaced.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert undone.result_document_hash == added.result_document_hash
    assert redone.result_document_hash == replaced.result_document_hash


def test_remove_behavior_rule_cleans_flow_layout_and_restores_exact_indexes() -> None:
    document = procurement_document()
    added = execute_command_batch(
        document,
        _add_behavior_rule_batch(
            "submit-rule",
            _behavior_rule_definition(
                "submit-rule",
                primary_targets=("page-detail", "page-list"),
            ),
        ),
        draft_id=fixture_id("behavior-rule-remove-draft"),
        client_request_id=fixture_id("behavior-rule-remove-add"),
    )
    rule_id = added.document.runtime.rules[0].id
    positioned = execute_command_batch(
        added.document,
        _set_runtime_flow_position_batch(rule_id, x=-320, y=480),
        draft_id=fixture_id("behavior-rule-remove-draft"),
        client_request_id=fixture_id("behavior-rule-remove-position"),
    )
    removed = execute_command_batch(
        positioned.document,
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "删除行为规则",
                "commands": [{"kind": "removeBehaviorRule", "ruleId": rule_id}],
            }
        ),
        draft_id=fixture_id("behavior-rule-remove-draft"),
        client_request_id=fixture_id("behavior-rule-remove-request"),
    )

    assert removed.document.runtime.rules == []
    assert removed.document.flows == []
    assert removed.document.runtime.flow_layout is None
    inverse_payload = removed.inverse_commands.model_dump(mode="json", by_alias=True)
    inverse_commands = inverse_payload["commands"]
    assert isinstance(inverse_commands, list)
    snapshot = inverse_commands[0]["snapshot"]
    assert snapshot["ruleIndex"] == 0
    assert [entry["index"] for entry in snapshot["flows"]] == [0, 1]
    assert snapshot["flowLayoutPosition"] == {
        "nodeId": rule_id,
        "x": -320,
        "y": 480,
    }
    restored = apply_inverse_commands(removed.document, removed.inverse_commands)
    assert prototype_contracts.canonical_model_json(restored) == (
        prototype_contracts.canonical_model_json(positioned.document)
    )
    undone = execute_inverse_command_batch(removed.document, removed.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert undone.result_document_hash == positioned.result_document_hash
    assert redone.result_document_hash == removed.result_document_hash


def test_remove_behavior_rule_undo_restores_interleaved_global_flow_indexes() -> None:
    document = procurement_document()
    first = execute_command_batch(
        document,
        _add_behavior_rule_batch(
            "button-rule",
            _behavior_rule_definition(
                "button-rule",
                primary_targets=("page-detail", "page-list"),
            ),
        ),
        draft_id=fixture_id("behavior-rule-interleaved-draft"),
        client_request_id=fixture_id("behavior-rule-interleaved-first"),
    )
    second = execute_command_batch(
        first.document,
        _add_behavior_rule_batch(
            "table-rule",
            _behavior_rule_definition(
                "table-rule",
                primary_targets=("page-list", "page-create"),
                node_key="table-list",
                event="rowActivated",
            ),
        ),
        draft_id=fixture_id("behavior-rule-interleaved-draft"),
        client_request_id=fixture_id("behavior-rule-interleaved-second"),
    )
    button_rule_id = second.document.runtime.rules[0].id
    button_flows = [flow for flow in second.document.flows if flow.rule_id == button_rule_id]
    table_flows = [flow for flow in second.document.flows if flow.rule_id != button_rule_id]
    interleaved_payload = second.document.model_dump(mode="json", by_alias=True)
    interleaved_payload["flows"] = [
        button_flows[0].model_dump(mode="json", by_alias=True),
        table_flows[0].model_dump(mode="json", by_alias=True),
        button_flows[1].model_dump(mode="json", by_alias=True),
        table_flows[1].model_dump(mode="json", by_alias=True),
    ]
    interleaved = PrototypeDocumentV1.model_validate(
        interleaved_payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    original_flow_ids = [flow.id for flow in interleaved.flows]
    replaced = execute_command_batch(
        interleaved,
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "更新交错流程规则说明",
                "commands": [
                    {
                        "kind": "replaceBehaviorRule",
                        "ruleId": button_rule_id,
                        "definition": {
                            **_behavior_rule_definition(
                                "button-rule",
                                primary_targets=("page-detail", "page-list"),
                            ),
                            "effects": [
                                {
                                    "kind": "navigate",
                                    "targetPageId": fixture_id("page-detail"),
                                },
                                {
                                    "kind": "navigate",
                                    "targetPageId": fixture_id("page-list"),
                                },
                                {
                                    "kind": "notify",
                                    "level": "success",
                                    "message": "流程已更新",
                                },
                            ],
                        },
                    }
                ],
            }
        ),
        draft_id=fixture_id("behavior-rule-interleaved-draft"),
        client_request_id=fixture_id("behavior-rule-interleaved-replace"),
    )
    assert [flow.id for flow in replaced.document.flows] == original_flow_ids
    assert [
        index
        for index, flow in enumerate(replaced.document.flows)
        if flow.rule_id == button_rule_id
    ] == [0, 2]
    assert prototype_contracts.canonical_model_json(
        apply_inverse_commands(replaced.document, replaced.inverse_commands)
    ) == prototype_contracts.canonical_model_json(interleaved)
    original_json = prototype_contracts.canonical_model_json(replaced.document)

    removed = execute_command_batch(
        replaced.document,
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "删除交错流程规则",
                "commands": [{"kind": "removeBehaviorRule", "ruleId": button_rule_id}],
            }
        ),
        draft_id=fixture_id("behavior-rule-interleaved-draft"),
        client_request_id=fixture_id("behavior-rule-interleaved-remove"),
    )
    inverse_payload = removed.inverse_commands.model_dump(mode="json", by_alias=True)
    inverse_commands = inverse_payload["commands"]
    assert isinstance(inverse_commands, list)
    snapshot = inverse_commands[0]["snapshot"]
    assert [entry["index"] for entry in snapshot["flows"]] == [0, 2]

    restored = apply_inverse_commands(removed.document, removed.inverse_commands)
    assert [flow.id for flow in restored.flows] == original_flow_ids
    assert prototype_contracts.canonical_model_json(restored) == original_json
    undone = execute_inverse_command_batch(removed.document, removed.inverse_commands)
    assert undone.result_document_hash == replaced.result_document_hash


def test_document_rejects_incomplete_duplicate_or_drifting_rule_flow_projections() -> None:
    added = execute_command_batch(
        procurement_document(),
        _add_behavior_rule_batch(
            "submit-rule",
            _behavior_rule_definition("submit-rule"),
        ),
        draft_id=fixture_id("behavior-rule-projection-draft"),
        client_request_id=fixture_id("behavior-rule-projection-request"),
    )
    payload = added.document.model_dump(mode="json", by_alias=True)
    candidates: list[dict[str, object]] = []

    missing = deepcopy(payload)
    flows = missing["flows"]
    assert isinstance(flows, list)
    flows.clear()
    candidates.append(missing)

    duplicate = deepcopy(payload)
    flows = duplicate["flows"]
    assert isinstance(flows, list)
    copied = deepcopy(flows[0])
    assert isinstance(copied, dict)
    copied["id"] = fixture_id("duplicate-rule-flow")
    copied["key"] = "duplicate-rule-flow"
    flows.append(copied)
    candidates.append(duplicate)

    drifting_source = deepcopy(payload)
    flows = drifting_source["flows"]
    assert isinstance(flows, list)
    flow = flows[0]
    assert isinstance(flow, dict)
    flow["fromNodeId"] = fixture_id("title-detail")
    candidates.append(drifting_source)

    for candidate in candidates:
        with pytest.raises(ValidationError):
            PrototypeDocumentV1.model_validate(
                candidate,
                strict=True,
                by_alias=True,
                by_name=False,
            )


def test_behavior_rule_validation_fails_closed_for_references_and_trigger_types() -> None:
    document = procurement_document()
    invalid_definitions = [
        _behavior_rule_definition("table-click", node_key="table-list", event="click"),
        _behavior_rule_definition("unknown-node", node_key="missing-node"),
        _behavior_rule_definition("unknown-page", primary_targets=("missing-page",)),
    ]
    for definition in invalid_definitions:
        key = definition["key"]
        assert isinstance(key, str)
        with pytest.raises(StructuredPrototypeContractError) as error:
            execute_command_batch(
                document,
                _add_behavior_rule_batch(key, definition),
                draft_id=fixture_id("behavior-rule-invalid-draft"),
                client_request_id=fixture_id(f"behavior-rule-invalid-{key}"),
            )
        assert error.value.code == "command_result_invalid"

    first = execute_command_batch(
        document,
        _add_behavior_rule_batch(
            "first-rule",
            _behavior_rule_definition("first-rule", primary_targets=()),
        ),
        draft_id=fixture_id("behavior-rule-trigger-draft"),
        client_request_id=fixture_id("behavior-rule-trigger-first"),
    )
    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            first.document,
            _add_behavior_rule_batch(
                "second-rule",
                _behavior_rule_definition("second-rule", primary_targets=()),
            ),
            draft_id=fixture_id("behavior-rule-trigger-draft"),
            client_request_id=fixture_id("behavior-rule-trigger-second"),
        )
    assert error.value.code == "command_result_invalid"

    disabled = execute_command_batch(
        first.document,
        _add_behavior_rule_batch(
            "disabled-rule",
            _behavior_rule_definition(
                "disabled-rule",
                primary_targets=(),
                enabled=False,
            ),
        ),
        draft_id=fixture_id("behavior-rule-trigger-draft"),
        client_request_id=fixture_id("behavior-rule-trigger-disabled"),
    )
    assert [rule.enabled for rule in disabled.document.runtime.rules] == [True, False]


def test_behavior_rule_submit_trigger_requires_a_button_inside_a_form() -> None:
    inside_form = execute_command_batch(
        procurement_document(),
        _add_behavior_rule_batch(
            "form-submit-rule",
            _behavior_rule_definition(
                "form-submit-rule",
                primary_targets=(),
                event="submit",
            ),
        ),
        draft_id=fixture_id("behavior-rule-submit-inside-draft"),
        client_request_id=fixture_id("behavior-rule-submit-inside-request"),
    )
    assert inside_form.document.runtime.rules[0].trigger.event == "submit"

    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    detail_page = pages[2]
    assert isinstance(detail_page, dict)
    root = detail_page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    children.append(
        {
            "id": fixture_id("outside-submit-button"),
            "name": "表单外提交",
            "visibility": "visible",
            "layoutItem": _layout(),
            "responsive": [],
            "type": "Button",
            "label": "提交",
            "variant": "primary",
            "size": "medium",
            "disabled": False,
            "iconName": None,
        }
    )
    outside_form_document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    invalid_document_payload = deepcopy(payload)
    invalid_runtime = invalid_document_payload["runtime"]
    assert isinstance(invalid_runtime, dict)
    invalid_definition = _behavior_rule_definition(
        "persisted-outside-submit-rule",
        primary_targets=(),
        node_key="outside-submit-button",
        event="submit",
    )
    invalid_runtime["rules"] = [
        {"id": fixture_id("persisted-outside-submit-rule"), **invalid_definition}
    ]
    with pytest.raises(ValidationError, match="Button inside a Form"):
        PrototypeDocumentV1.model_validate(
            invalid_document_payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    click = execute_command_batch(
        outside_form_document,
        _add_behavior_rule_batch(
            "outside-click-rule",
            _behavior_rule_definition(
                "outside-click-rule",
                primary_targets=(),
                node_key="outside-submit-button",
            ),
        ),
        draft_id=fixture_id("behavior-rule-outside-click-draft"),
        client_request_id=fixture_id("behavior-rule-outside-click-request"),
    )
    assert click.document.runtime.rules[0].trigger.event == "click"

    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            outside_form_document,
            _add_behavior_rule_batch(
                "outside-submit-rule",
                _behavior_rule_definition(
                    "outside-submit-rule",
                    primary_targets=(),
                    node_key="outside-submit-button",
                    event="submit",
                ),
            ),
            draft_id=fixture_id("behavior-rule-submit-outside-draft"),
            client_request_id=fixture_id("behavior-rule-submit-outside-request"),
        )
    assert error.value.code == "command_result_invalid"


def test_behavior_rule_batch_is_atomic_and_command_count_is_bounded() -> None:
    document = procurement_document()
    base_hash = document_hash(document)
    definition = _behavior_rule_definition("atomic-rule")
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "原子新增后失败",
            "commands": [
                {
                    "kind": "addBehaviorRule",
                    "newRuleKey": "atomic-rule",
                    "definition": definition,
                },
                {
                    "kind": "removeBehaviorRule",
                    "ruleId": fixture_id("missing-rule"),
                },
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            batch,
            draft_id=fixture_id("behavior-rule-atomic-draft"),
            client_request_id=fixture_id("behavior-rule-atomic-request"),
        )
    assert error.value.code == "command_target_missing"
    assert document_hash(document) == base_hash
    assert document.runtime.rules == []
    assert document.flows == []

    collision_draft_id = fixture_id("behavior-rule-flow-key-collision-draft")
    collision_request_id = fixture_id("behavior-rule-flow-key-collision-request")
    collision_rule_id = str(
        uuid5(
            prototype_contracts.PROTOTYPE_ENTITY_NAMESPACE,
            f"{collision_draft_id}:{collision_request_id}:rule:collision-rule",
        )
    )
    collision_flow_id = str(uuid5(UUID(collision_rule_id), fixture_id("page-detail")))
    collision_flow_key = f"flow-{UUID(collision_flow_id).hex}"
    collision_batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "拒绝批次内派生流程 key 冲突",
            "commands": [
                {
                    "kind": "insertNode",
                    "parent": {
                        "kind": "existing",
                        "nodeId": fixture_id("root-detail"),
                    },
                    "slot": None,
                    "index": 1,
                    "node": {
                        "newNodeKey": collision_flow_key,
                        "type": "Text",
                        "name": "冲突占位",
                        "visibility": "visible",
                        "layoutItem": _layout(),
                        "responsive": [],
                        "content": "冲突",
                        "semantic": "body",
                        "tone": "default",
                    },
                },
                {
                    "kind": "addBehaviorRule",
                    "newRuleKey": "collision-rule",
                    "definition": _behavior_rule_definition("collision-rule"),
                },
            ],
        }
    )
    with pytest.raises(StructuredPrototypeContractError) as collision_error:
        execute_command_batch(
            document,
            collision_batch,
            draft_id=collision_draft_id,
            client_request_id=collision_request_id,
        )
    assert collision_error.value.code == "command_new_key_duplicate"
    assert document_hash(document) == base_hash

    commands = [
        {
            "kind": "addBehaviorRule",
            "newRuleKey": f"rule-{index}",
            "definition": _behavior_rule_definition(
                f"rule-{index}",
                primary_targets=(),
                enabled=False,
            ),
        }
        for index in range(101)
    ]
    with pytest.raises(ValidationError):
        _parse_batch(
            {
                "commandContractVersion": 1,
                "summary": "超出命令数量上限",
                "commands": commands,
            }
        )


def _page_crud_reference_document() -> PrototypeDocumentV1:
    payload, table = _dynamic_table_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    list_page = pages[0]
    assert isinstance(list_page, dict)
    root = list_page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    root_layout = root["layoutItem"]
    assert isinstance(root_layout, dict)
    root_layout["width"] = {"unit": "px", "value": "1200"}
    root_layout["height"] = {"unit": "px", "value": "800"}
    for field in ("direction", "gap", "align", "justify", "padding"):
        root.pop(field)
    root["type"] = "Freeform"
    root["grids"] = [
        {
            "id": fixture_id("page-crud-grid"),
            "version": 1,
            "type": "square",
            "visible": True,
            "snapEnabled": True,
            "origin": {"x": "0", "y": "0"},
            "params": {
                "size": "16",
                "colorTokenKey": "primary",
                "opacity": "0.25",
            },
        }
    ]
    for index, child in enumerate(children):
        assert isinstance(child, dict)
        layout = child["layoutItem"]
        assert isinstance(layout, dict)
        layout["position"] = {"x": str(24 + index * 360), "y": "32"}
    table["rows"] = [
        {
            "id": fixture_id("page-crud-row"),
            "cells": [
                {"columnKey": "title", "value": "办公电脑采购"},
                {"columnKey": "status", "value": "pending"},
            ],
        }
    ]
    button_id = fixture_id("page-crud-button")
    button_layout = _layout()
    button_layout["position"] = {"x": "24", "y": "180"}
    children.append(
        {
            "id": button_id,
            "type": "Button",
            "name": "页面动作",
            "visibility": "visible",
            "layoutItem": button_layout,
            "responsive": [],
            "label": "打开详情",
            "variant": "primary",
            "size": "medium",
            "disabled": False,
            "iconName": None,
        }
    )

    page_list_id = fixture_id("page-list")
    page_detail_id = fixture_id("page-detail")
    navigation = payload["navigation"]
    assert isinstance(navigation, dict)
    navigation_items = navigation["items"]
    assert isinstance(navigation_items, list)
    navigation_items.append(
        {
            "id": fixture_id("page-crud-nav-secondary"),
            "key": "purchase-list-secondary",
            "label": "采购列表快捷入口",
            "targetPageId": page_list_id,
        }
    )

    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    rule_id = fixture_id("page-crud-rule")
    runtime["rules"] = [
        {
            "id": rule_id,
            "key": "page-crud-rule",
            "enabled": True,
            "trigger": {"kind": "nodeEvent", "nodeId": button_id, "event": "click"},
            "guard": {"kind": "roleIs", "roleId": fixture_id("role-applicant")},
            "effects": [
                {"kind": "navigate", "targetPageId": page_list_id},
                {"kind": "navigate", "targetPageId": page_detail_id},
            ],
            "guardFalseEffects": [
                {"kind": "navigate", "targetPageId": page_list_id},
            ],
        }
    ]
    runtime["flowLayout"] = {
        "nodes": sorted(
            [
                {"nodeId": page_list_id, "x": 120, "y": 80},
                {"nodeId": rule_id, "x": 420, "y": 180},
            ],
            key=lambda item: str(item["nodeId"]),
        )
    }
    payload["flows"] = [
        {
            "id": fixture_id("page-crud-flow-self"),
            "key": "page-crud-flow-self",
            "ruleId": rule_id,
            "fromNodeId": button_id,
            "toPageId": page_list_id,
        },
        {
            "id": fixture_id("page-crud-flow-detail"),
            "key": "page-crud-flow-detail",
            "ruleId": rule_id,
            "fromNodeId": button_id,
            "toPageId": page_detail_id,
        },
    ]
    return PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _page_command(command: dict[str, object], summary: str) -> DomainCommandBatchV1:
    return _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": summary,
            "commands": [command],
        }
    )


def test_page_add_is_deterministic_freeform_navigable_and_exactly_reversible() -> None:
    document = procurement_document()
    command = _page_command(
        {
            "kind": "addPage",
            "afterPageId": fixture_id("page-list"),
            "newPageKey": "page-add-list",
            "title": "Blank workspace",
            "includeInNavigation": True,
        },
        "Add a blank page",
    )
    kwargs = {
        "draft_id": fixture_id("page-add-draft"),
        "client_request_id": fixture_id("page-add-request"),
    }
    first = execute_command_batch(document, command, **kwargs)
    second = execute_command_batch(document, command, **kwargs)
    assert first.document == second.document
    assert first.allocated_entity_ids == second.allocated_entity_ids
    allocated = dict(first.allocated_entity_ids)
    page_id = allocated["page-add-list"]
    assert allocated["page-add-list:root"]
    page = next(page for page in first.document.pages if page.id == page_id)
    assert isinstance(page.root, FreeformNodeV1)
    assert page.root.children == []
    assert page.viewport == document.pages[0].viewport
    assert page.root.layout_item.width.value == str(page.viewport.width)
    assert page.root.layout_item.height.value == str(page.viewport.height)
    assert first.document.pages[1].id == page_id
    assert first.document.runtime.page_ids == [page.id for page in first.document.pages]
    navigation_items = [
        item for item in first.document.navigation.items if item.target_page_id == page_id
    ]
    assert len(navigation_items) == 1
    assert navigation_items[0].label == "Blank workspace"
    assert allocated["page-add-list:navigation"] == navigation_items[0].id
    assert fixture_id("page-list") in first.affected_entity_ids
    undone = execute_inverse_command_batch(first.document, first.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert document_hash(undone.document) == document_hash(document)
    assert document_hash(redone.document) == document_hash(first.document)


def test_page_add_generates_unique_keys_routes_and_optional_navigation() -> None:
    document = procurement_document()
    batch = _parse_batch(
        {
            "commandContractVersion": 1,
            "summary": "Add two deterministic pages",
            "commands": [
                {
                    "kind": "addPage",
                    "afterPageId": fixture_id("page-list"),
                    "newPageKey": "page-add-first",
                    "title": "采购列表",
                    "includeInNavigation": False,
                },
                {
                    "kind": "addPage",
                    "afterPageId": fixture_id("page-list"),
                    "newPageKey": "page-add-second",
                    "title": "采购列表",
                    "includeInNavigation": False,
                },
            ],
        }
    )
    result = execute_command_batch(
        document,
        batch,
        draft_id=fixture_id("page-add-unique-draft"),
        client_request_id=fixture_id("page-add-unique-request"),
    )
    allocated = dict(result.allocated_entity_ids)
    added_page_ids = {allocated["page-add-first"], allocated["page-add-second"]}
    added_pages = [page for page in result.document.pages if page.id in added_page_ids]
    assert {page.key for page in added_pages} == {"page", "page-2"}
    assert {page.route for page in added_pages} == {"/page", "/page-2"}
    assert all(
        item.target_page_id not in added_page_ids for item in result.document.navigation.items
    )


def test_page_duplicate_remaps_owned_graph_and_round_trips_exactly() -> None:
    document = _page_crud_reference_document()
    command = _page_command(
        {
            "kind": "duplicatePage",
            "pageId": fixture_id("page-list"),
            "newPageKey": "page-duplicate-list",
            "title": "采购申请列表副本",
        },
        "Duplicate the list page",
    )
    kwargs = {
        "draft_id": fixture_id("page-duplicate-draft"),
        "client_request_id": fixture_id("page-duplicate-request"),
    }
    first = execute_command_batch(document, command, **kwargs)
    second = execute_command_batch(document, command, **kwargs)
    assert first.document == second.document
    assert first.allocated_entity_ids == second.allocated_entity_ids
    allocated = dict(first.allocated_entity_ids)
    duplicate_page_id = allocated["page-duplicate-list"]
    duplicate_page = next(page for page in first.document.pages if page.id == duplicate_page_id)
    assert first.document.pages[1].id == duplicate_page_id
    assert first.document.runtime.page_ids == [page.id for page in first.document.pages]
    source_node_ids = prototype_contracts._node_id_set(document.pages[0].root)
    duplicate_node_ids = prototype_contracts._node_id_set(duplicate_page.root)
    assert source_node_ids.isdisjoint(duplicate_node_ids)
    duplicate_root = duplicate_page.root
    assert isinstance(duplicate_root, FreeformNodeV1)
    source_root = document.pages[0].root
    assert isinstance(source_root, FreeformNodeV1)
    assert (
        duplicate_root.grids[0].id
        == allocated[f"page-duplicate-list:grid:{source_root.grids[0].id}"]
    )
    source_table = next(node for node in source_root.children if node.type == "Table")
    duplicate_table = next(node for node in duplicate_root.children if node.type == "Table")
    assert source_table.type == "Table"
    assert duplicate_table.type == "Table"
    assert (
        duplicate_table.rows[0].id
        == allocated[f"page-duplicate-list:row:{source_table.rows[0].id}"]
    )

    duplicate_navigation = [
        item for item in first.document.navigation.items if item.target_page_id == duplicate_page_id
    ]
    assert len(duplicate_navigation) == 2
    assert all(item.label == "采购申请列表副本" for item in duplicate_navigation)
    source_binding = document.runtime.view_bindings[0]
    duplicate_binding_id = allocated[f"page-duplicate-list:binding:{source_binding.id}"]
    duplicate_binding = next(
        binding
        for binding in first.document.runtime.view_bindings
        if binding.id == duplicate_binding_id
    )
    assert duplicate_binding.node_id == duplicate_table.id

    source_rule = document.runtime.rules[0]
    duplicate_rule_id = allocated[f"page-duplicate-list:rule:{source_rule.id}"]
    duplicate_rule = next(
        rule for rule in first.document.runtime.rules if rule.id == duplicate_rule_id
    )
    assert (
        duplicate_rule.trigger.node_id
        == allocated[f"page-duplicate-list:node:{source_rule.trigger.node_id}"]
    )
    assert [
        effect.target_page_id for effect in duplicate_rule.effects if effect.kind == "navigate"
    ] == [duplicate_page_id, fixture_id("page-detail")]
    assert [
        effect.target_page_id
        for effect in duplicate_rule.guard_false_effects
        if effect.kind == "navigate"
    ] == [duplicate_page_id]
    duplicate_flows = [flow for flow in first.document.flows if flow.rule_id == duplicate_rule_id]
    assert [flow.to_page_id for flow in duplicate_flows] == [
        duplicate_page_id,
        fixture_id("page-detail"),
    ]
    assert [flow.id for flow in duplicate_flows] == [
        str(uuid5(UUID(duplicate_rule_id), duplicate_page_id)),
        str(uuid5(UUID(duplicate_rule_id), fixture_id("page-detail"))),
    ]
    assert first.document.runtime.flow_layout is not None
    positions = {
        position.node_id: (position.x, position.y)
        for position in first.document.runtime.flow_layout.nodes
    }
    assert positions[duplicate_page_id] == positions[fixture_id("page-list")]
    assert positions[duplicate_rule_id] == positions[source_rule.id]
    assert first.document.runtime.forms == document.runtime.forms
    assert first.document.runtime.entity_schemas == document.runtime.entity_schemas
    assert first.document.runtime.scenarios == document.runtime.scenarios
    assert fixture_id("page-list") in first.affected_entity_ids
    undone = execute_inverse_command_batch(first.document, first.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert document_hash(undone.document) == document_hash(document)
    assert document_hash(redone.document) == document_hash(first.document)


def test_page_rename_syncs_navigation_preserves_route_and_restores_original_labels() -> None:
    document = _page_crud_reference_document()
    source_page = document.pages[0]
    original_labels = [
        item.label for item in document.navigation.items if item.target_page_id == source_page.id
    ]
    result = execute_command_batch(
        document,
        _page_command(
            {"kind": "renamePage", "pageId": source_page.id, "title": "采购中心"},
            "Rename page",
        ),
        draft_id=fixture_id("page-rename-draft"),
        client_request_id=fixture_id("page-rename-request"),
    )
    renamed = next(page for page in result.document.pages if page.id == source_page.id)
    assert renamed.title == "采购中心"
    assert renamed.route == source_page.route
    assert renamed.key == source_page.key
    assert {
        item.label
        for item in result.document.navigation.items
        if item.target_page_id == source_page.id
    } == {"采购中心"}
    restored = apply_inverse_commands(result.document, result.inverse_commands)
    assert [
        item.label for item in restored.navigation.items if item.target_page_id == source_page.id
    ] == original_labels
    assert document_hash(restored) == document_hash(document)


def test_page_delete_cascades_owned_projections_and_round_trips_exactly() -> None:
    document = _page_crud_reference_document()
    page_id = fixture_id("page-list")
    source_page = document.pages[0]
    source_node_ids = prototype_contracts._node_id_set(source_page.root)
    source_rule_ids = {
        rule.id for rule in document.runtime.rules if rule.trigger.node_id in source_node_ids
    }
    result = execute_command_batch(
        document,
        _page_command({"kind": "deletePage", "pageId": page_id}, "Delete page"),
        draft_id=fixture_id("page-delete-draft"),
        client_request_id=fixture_id("page-delete-request"),
    )
    assert page_id not in {page.id for page in result.document.pages}
    assert page_id not in result.document.runtime.page_ids
    assert all(item.target_page_id != page_id for item in result.document.navigation.items)
    assert all(
        binding.node_id not in source_node_ids for binding in result.document.runtime.view_bindings
    )
    assert all(rule.id not in source_rule_ids for rule in result.document.runtime.rules)
    assert all(flow.rule_id not in source_rule_ids for flow in result.document.flows)
    assert result.document.runtime.flow_layout is None
    assert result.document.runtime.forms == document.runtime.forms
    assert result.document.runtime.entity_schemas == document.runtime.entity_schemas
    assert result.document.runtime.scenarios == document.runtime.scenarios
    undone = execute_inverse_command_batch(result.document, result.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert document_hash(undone.document) == document_hash(document)
    assert document_hash(redone.document) == document_hash(result.document)


def test_page_delete_supports_inverse_snapshots_larger_than_forward_request_limit() -> None:
    payload = _page_crud_reference_document().model_dump(mode="json", by_alias=True)
    pages = payload["pages"]
    assert isinstance(pages, list)
    page = pages[0]
    assert isinstance(page, dict)
    root = page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    for index in range(35):
        layout = _layout()
        layout["position"] = {"x": "24", "y": str(240 + index)}
        content_prefix = f"{index}:"
        children.append(
            {
                "id": fixture_id(f"large-page-text-{index}"),
                "type": "Text",
                "name": f"Large text {index}",
                "visibility": "visible",
                "layoutItem": layout,
                "responsive": [],
                "content": content_prefix + "x" * (8_000 - len(content_prefix)),
                "semantic": "body",
                "tone": "default",
            }
        )
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )

    result = execute_command_batch(
        document,
        _page_command(
            {"kind": "deletePage", "pageId": fixture_id("page-list")},
            "Delete large page",
        ),
        draft_id=fixture_id("large-page-delete-draft"),
        client_request_id=fixture_id("large-page-delete-request"),
    )
    assert (
        len(prototype_contracts.canonical_model_json(result.inverse_commands).encode("utf-8"))
        > prototype_contracts.PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES
    )
    undone = execute_inverse_command_batch(result.document, result.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert document_hash(undone.document) == document_hash(document)
    assert document_hash(redone.document) == document_hash(result.document)


@pytest.mark.parametrize("navigate_list", ["effects", "guardFalseEffects"])
def test_page_delete_names_external_inbound_navigation_rule(navigate_list: str) -> None:
    payload = procurement_document_payload()
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    effects: list[dict[str, object]] = [{"kind": "notify", "level": "info", "message": "保留页面"}]
    guard_false_effects: list[dict[str, object]] = []
    target_effect: dict[str, object] = {
        "kind": "navigate",
        "targetPageId": fixture_id("page-detail"),
    }
    if navigate_list == "effects":
        effects = [target_effect]
    else:
        guard_false_effects = [target_effect]
    rule_id = fixture_id(f"external-page-rule-{navigate_list}")
    runtime["rules"] = [
        {
            "id": rule_id,
            "key": f"external-{navigate_list.lower()}",
            "enabled": True,
            "trigger": {
                "kind": "nodeEvent",
                "nodeId": fixture_id("button-submit"),
                "event": "click",
            },
            "guard": None,
            "effects": effects,
            "guardFalseEffects": guard_false_effects,
        }
    ]
    payload["flows"] = [
        {
            "id": fixture_id(f"external-page-flow-{navigate_list}"),
            "key": f"external-flow-{navigate_list.lower()}",
            "ruleId": rule_id,
            "fromNodeId": fixture_id("button-submit"),
            "toPageId": fixture_id("page-detail"),
        }
    ]
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    with pytest.raises(StructuredPrototypeContractError) as error:
        execute_command_batch(
            document,
            _page_command(
                {"kind": "deletePage", "pageId": fixture_id("page-detail")},
                "Delete referenced page",
            ),
            draft_id=fixture_id("page-delete-inbound-draft"),
            client_request_id=fixture_id(f"page-delete-inbound-{navigate_list}"),
        )
    assert error.value.code == "command_page_inbound_navigation"
    assert f"external-{navigate_list.lower()}" in str(error.value)


def test_page_delete_refuses_scenario_start_and_final_page_with_names() -> None:
    document = procurement_document()
    with pytest.raises(StructuredPrototypeContractError) as scenario_error:
        execute_command_batch(
            document,
            _page_command(
                {"kind": "deletePage", "pageId": fixture_id("page-create")},
                "Delete scenario page",
            ),
            draft_id=fixture_id("page-delete-scenario-draft"),
            client_request_id=fixture_id("page-delete-scenario-request"),
        )
    assert scenario_error.value.code == "command_page_scenario_start"
    assert "purchase-happy-path" in str(scenario_error.value)

    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    payload["pages"] = [pages[0]]
    navigation = payload["navigation"]
    assert isinstance(navigation, dict)
    navigation_items = navigation["items"]
    assert isinstance(navigation_items, list)
    navigation["items"] = [navigation_items[0]]
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["pageIds"] = [fixture_id("page-list")]
    scenarios = runtime["scenarios"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    scenario["startPageId"] = fixture_id("page-list")
    single_page = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    with pytest.raises(StructuredPrototypeContractError) as final_error:
        execute_command_batch(
            single_page,
            _page_command(
                {"kind": "deletePage", "pageId": fixture_id("page-list")},
                "Delete final page",
            ),
            draft_id=fixture_id("page-delete-final-draft"),
            client_request_id=fixture_id("page-delete-final-request"),
        )
    assert final_error.value.code == "command_last_page_delete"


def test_node_name_update_is_nonblank_and_exactly_reversible() -> None:
    document = procurement_document()
    node_id = fixture_id("title-list")
    result = execute_command_batch(
        document,
        _page_command(
            {"kind": "updateNodeName", "nodeId": node_id, "name": "列表主标题"},
            "Rename node",
        ),
        draft_id=fixture_id("node-name-draft"),
        client_request_id=fixture_id("node-name-request"),
    )
    assert prototype_contracts._require_node(result.document, node_id).name == "列表主标题"
    assert document_hash(apply_inverse_commands(result.document, result.inverse_commands)) == (
        document_hash(document)
    )
    with pytest.raises(ValidationError):
        _page_command(
            {"kind": "updateNodeName", "nodeId": node_id, "name": "   "},
            "Reject blank node name",
        )


def test_node_name_update_can_repair_and_restore_a_legacy_whitespace_name() -> None:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    page = pages[0]
    assert isinstance(page, dict)
    root = page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    node = children[0]
    assert isinstance(node, dict)
    node["name"] = "   "
    document = PrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )
    node_id = fixture_id("title-list")

    result = execute_command_batch(
        document,
        _page_command(
            {"kind": "updateNodeName", "nodeId": node_id, "name": "Repaired name"},
            "Repair legacy node name",
        ),
        draft_id=fixture_id("legacy-node-name-draft"),
        client_request_id=fixture_id("legacy-node-name-request"),
    )
    assert prototype_contracts._require_node(result.document, node_id).name == "Repaired name"
    assert result.inverse_commands.commands[0].kind == "restoreNodeName"
    undone = execute_inverse_command_batch(result.document, result.inverse_commands)
    redone = execute_inverse_command_batch(undone.document, undone.inverse_commands)
    assert prototype_contracts._require_node(undone.document, node_id).name == "   "
    assert document_hash(undone.document) == document_hash(document)
    assert document_hash(redone.document) == document_hash(result.document)


def test_runtime_page_order_is_exact_and_reorder_updates_it() -> None:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    payload["pages"] = [pages[1], pages[0], pages[2]]
    with pytest.raises(ValidationError, match="runtime page IDs must match document page order"):
        PrototypeDocumentV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    document = procurement_document()
    result = execute_command_batch(
        document,
        _page_command(
            {
                "kind": "reorderPage",
                "pageId": fixture_id("page-detail"),
                "targetIndex": 0,
            },
            "Reorder page",
        ),
        draft_id=fixture_id("runtime-page-order-draft"),
        client_request_id=fixture_id("runtime-page-order-request"),
    )
    assert result.document.runtime.page_ids == [page.id for page in result.document.pages]
