from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.application.structured_prototype_contracts import StructuredPrototypeContractError
from app.application.structured_prototype_generation_contracts import (
    GeneratedPageV1,
    GenerationBlueprintV1,
    GenerationFoundationV1,
    parse_generation_artifact,
)


def blueprint_payload() -> dict[str, object]:
    return {
        "contractVersion": 1,
        "documentTitle": "采购协同",
        "productIntent": "提交和审批采购申请",
        "outputLocale": "zh-CN",
        "foundationIntent": {
            "visualLanguage": "安静、紧凑的企业工作台",
            "density": "compact",
            "responsiveStrategy": "移动端单列, 桌面端保持内容宽度",
        },
        "pages": [
            {
                "pageKey": "purchase-list",
                "title": "采购申请列表",
                "route": "/purchases",
                "purpose": "查看全部申请",
                "navigationGroupKey": "procurement",
            },
            {
                "pageKey": "purchase-create",
                "title": "创建采购申请",
                "route": "/purchases/new",
                "purpose": "填写并提交申请",
                "navigationGroupKey": "procurement",
            },
            {
                "pageKey": "purchase-detail",
                "title": "采购申请详情",
                "route": "/purchases/detail",
                "purpose": "查看并审批申请",
                "navigationGroupKey": "procurement",
            },
        ],
        "navigation": [
            {"key": "purchase-list", "label": "采购申请", "targetPageKey": "purchase-list"},
            {"key": "purchase-create", "label": "创建申请", "targetPageKey": "purchase-create"},
            {"key": "purchase-detail", "label": "申请详情", "targetPageKey": "purchase-detail"},
        ],
        "flowIntents": [
            {
                "key": "submit-request",
                "sourcePageKey": "purchase-create",
                "sourceNodeKey": "submit-request",
                "event": "submit",
                "targetPageKey": "purchase-detail",
            }
        ],
        "roleIntents": ["applicant", "manager"],
        "entityIntents": ["purchase-request"],
        "formIntents": ["create-purchase-request"],
        "scenarioIntents": ["purchase-approval-happy-path"],
        "startPageKeys": ["purchase-create"],
    }


def foundation_payload() -> dict[str, object]:
    return {
        "contractVersion": 1,
        "colors": [
            {"key": "primary", "value": "#126b5f"},
            {"key": "surface", "value": "#ffffff"},
        ],
        "spacing": [{"key": "panel-gap", "value": "16px"}],
        "componentTypes": ["Stack", "Form", "Text", "Input", "Button", "Table"],
        "sharedShellTitle": "采购协同",
        "contentConventions": "使用清晰、简短的企业采购文案",
    }


def page_payload() -> dict[str, object]:
    return {
        "contractVersion": 1,
        "pageKey": "purchase-create",
        "title": "创建采购申请",
        "route": "/purchases/new",
        "root": {
            "localKey": "create-root",
            "name": "创建申请页面",
            "visibility": "visible",
            "type": "Stack",
            "direction": "column",
            "gap": 16,
            "padding": 24,
            "children": [
                {
                    "localKey": "create-form",
                    "name": "采购申请表单",
                    "type": "Form",
                    "formKey": "create-purchase-request",
                    "gap": 12,
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
                            "localKey": "submit-request",
                            "name": "提交申请",
                            "type": "Button",
                            "label": "提交申请",
                            "variant": "primary",
                        },
                    ],
                }
            ],
        },
    }


def test_generation_contracts_accept_strict_mvp_artifacts() -> None:
    blueprint = GenerationBlueprintV1.model_validate(blueprint_payload(), strict=True)
    foundation = GenerationFoundationV1.model_validate(foundation_payload(), strict=True)
    page = GeneratedPageV1.model_validate(page_payload(), strict=True)

    assert [item.page_key for item in blueprint.pages] == [
        "purchase-list",
        "purchase-create",
        "purchase-detail",
    ]
    assert set(foundation.component_types) == {"Stack", "Form", "Text", "Input", "Button", "Table"}
    assert page.root.children[0].local_key == "create-form"


@pytest.mark.parametrize("duplicate_field", ["roleIntents", "startPageKeys"])
def test_blueprint_refuses_duplicate_semantic_keys(duplicate_field: str) -> None:
    payload = blueprint_payload()
    values = payload[duplicate_field]
    assert isinstance(values, list)
    values.append(values[0])

    with pytest.raises(ValueError, match="duplicate"):
        GenerationBlueprintV1.model_validate(payload, strict=True)


def test_foundation_refuses_duplicate_or_missing_component_type() -> None:
    payload = foundation_payload()
    payload["componentTypes"] = ["Stack", "Form", "Text", "Input", "Button", "Button"]

    with pytest.raises(ValueError, match="duplicate component type"):
        GenerationFoundationV1.model_validate(payload, strict=True)


def test_page_refuses_duplicate_local_key_anywhere_in_tree() -> None:
    payload = page_payload()
    root = payload["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    duplicate = deepcopy(children[0])
    children.append(duplicate)

    with pytest.raises(ValueError, match="duplicate page node local key"):
        GeneratedPageV1.model_validate(payload, strict=True)


def test_artifact_parser_refuses_unknown_fields() -> None:
    envelope = {
        "generationContractVersion": 1,
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
