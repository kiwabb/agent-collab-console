from __future__ import annotations

import pytest
from pydantic import ValidationError
from structured_prototype_fixtures import (
    fixture_id,
    procurement_document,
    procurement_document_payload,
)

from app.adapters.prototype_object_store import canonical_json_bytes
from app.application.structured_prototype_contracts import (
    DomainCommandBatchV1,
    PrototypeDocumentV1,
    StructuredPrototypeContractError,
    apply_inverse_commands,
    command_batch_hash,
    document_hash,
    execute_command_batch,
    parse_command_batch_json,
    parse_prototype_document_json,
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


def _parse_batch(payload: dict[str, object]) -> DomainCommandBatchV1:
    return DomainCommandBatchV1.model_validate(
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
