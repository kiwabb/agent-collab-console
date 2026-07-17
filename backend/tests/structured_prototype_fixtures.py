from __future__ import annotations

from uuid import UUID, uuid5

from app.application.structured_prototype_contracts import PrototypeDocumentV1

FIXTURE_NAMESPACE = UUID("add80290-85a3-50b4-97e3-ab2560b83177")


def fixture_id(key: str) -> str:
    return str(uuid5(FIXTURE_NAMESPACE, key))


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


def _common(key: str, name: str) -> dict[str, object]:
    return {
        "id": fixture_id(key),
        "name": name,
        "visibility": "visible",
        "layoutItem": _layout(),
        "responsive": [],
    }


def procurement_document_payload() -> dict[str, object]:
    page_list = fixture_id("page-list")
    page_create = fixture_id("page-create")
    page_detail = fixture_id("page-detail")
    form_create = fixture_id("form-create")
    role_applicant = fixture_id("role-applicant")
    return {
        "schemaVersion": 1,
        "id": fixture_id("document"),
        "title": "采购申请原型",
        "locale": "zh-CN",
        "settings": {
            "defaultViewport": "desktop",
            "theme": "light",
            "shell": {
                "kind": "sidebar",
                "title": "采购申请原型",
                "accentColorTokenKey": "primary",
                "navigationBackgroundColorTokenKey": "surface",
                "contentBackgroundColorTokenKey": "surface",
                "surfaceColorTokenKey": "surface",
                "navigationWidth": 240,
                "expandedMinWidth": 1024,
            },
        },
        "tokens": {
            "colors": [
                {"key": "primary", "value": "#2563eb"},
                {"key": "surface", "value": "#ffffff"},
            ],
            "spacing": [{"key": "panel-gap", "value": "16px"}],
        },
        "componentDefinitions": [],
        "pages": [
            {
                "id": page_list,
                "key": "purchase-list",
                "title": "采购申请列表",
                "route": "/purchases",
                "viewport": {"width": 1440, "height": 900},
                "root": {
                    **_common("root-list", "列表页面"),
                    "type": "Stack",
                    "direction": "column",
                    "gap": 16,
                    "align": "stretch",
                    "justify": "start",
                    "padding": {"top": 24, "right": 24, "bottom": 24, "left": 24},
                    "children": [
                        {
                            **_common("title-list", "列表标题"),
                            "type": "Text",
                            "content": "采购申请",
                            "semantic": "heading",
                            "tone": "default",
                        },
                        {
                            **_common("table-list", "申请表格"),
                            "type": "Table",
                            "columns": [
                                {"key": "title", "label": "申请事项"},
                                {"key": "status", "label": "状态"},
                            ],
                            "rows": [],
                            "density": "comfortable",
                        },
                    ],
                },
            },
            {
                "id": page_create,
                "key": "purchase-create",
                "title": "创建采购申请",
                "route": "/purchases/new",
                "viewport": {"width": 1440, "height": 900},
                "root": {
                    **_common("root-create", "创建页面"),
                    "type": "Stack",
                    "direction": "column",
                    "gap": 16,
                    "align": "stretch",
                    "justify": "start",
                    "padding": {"top": 24, "right": 24, "bottom": 24, "left": 24},
                    "children": [
                        {
                            **_common("form-node-create", "采购表单"),
                            "type": "Form",
                            "formDefinitionId": form_create,
                            "gap": 12,
                            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                            "children": [
                                {
                                    **_common("input-title", "申请事项输入框"),
                                    "type": "Input",
                                    "label": "申请事项",
                                    "placeholder": "请输入申请事项",
                                    "value": "",
                                    "inputType": "text",
                                    "required": True,
                                    "disabled": False,
                                    "formDefinitionId": form_create,
                                    "formFieldId": fixture_id("form-field-title"),
                                },
                                {
                                    **_common("button-submit", "提交按钮"),
                                    "type": "Button",
                                    "label": "提交申请",
                                    "variant": "primary",
                                    "size": "medium",
                                    "disabled": False,
                                    "iconName": None,
                                },
                            ],
                        }
                    ],
                },
            },
            {
                "id": page_detail,
                "key": "purchase-detail",
                "title": "采购申请详情",
                "route": "/purchases/detail",
                "viewport": {"width": 1440, "height": 900},
                "root": {
                    **_common("root-detail", "详情页面"),
                    "type": "Stack",
                    "direction": "column",
                    "gap": 16,
                    "align": "stretch",
                    "justify": "start",
                    "padding": {"top": 24, "right": 24, "bottom": 24, "left": 24},
                    "children": [
                        {
                            **_common("title-detail", "详情标题"),
                            "type": "Text",
                            "content": "采购申请详情",
                            "semantic": "heading",
                            "tone": "default",
                        }
                    ],
                },
            },
        ],
        "navigation": {
            "items": [
                {
                    "id": fixture_id("nav-list"),
                    "key": "purchase-list",
                    "label": "采购申请",
                    "targetPageId": page_list,
                },
                {
                    "id": fixture_id("nav-create"),
                    "key": "purchase-create",
                    "label": "创建申请",
                    "targetPageId": page_create,
                },
            ]
        },
        "flows": [],
        "runtime": {
            "runtimeSchemaVersion": 1,
            "pageIds": [page_list, page_create, page_detail],
            "roles": [
                {"id": role_applicant, "key": "applicant", "label": "申请人"},
            ],
            "variables": [],
            "entitySchemas": [],
            "forms": [
                {
                    "id": form_create,
                    "key": "purchase-create",
                    "fields": [
                        {
                            "id": fixture_id("form-field-title"),
                            "key": "title",
                            "valueType": "string",
                            "initialValue": {"type": "string", "value": ""},
                            "required": True,
                            "minInteger": None,
                        }
                    ],
                }
            ],
            "viewBindings": [],
            "rules": [],
            "scenarios": [
                {
                    "id": fixture_id("scenario-happy-path"),
                    "key": "purchase-happy-path",
                    "actorRoleId": role_applicant,
                    "startPageId": page_create,
                    "initialVariables": [],
                    "entityFixtures": [],
                    "allowSimulatedRoleSwitch": True,
                }
            ],
        },
        "assetRefs": [],
    }


def procurement_document() -> PrototypeDocumentV1:
    return PrototypeDocumentV1.model_validate(
        procurement_document_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )


def text_insert_batch_payload() -> dict[str, object]:
    auto = {"unit": "auto", "value": None}
    return {
        "commandContractVersion": 1,
        "summary": "添加审批说明",
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
                    "layoutItem": {
                        "width": auto,
                        "minWidth": None,
                        "maxWidth": None,
                        "height": auto,
                        "minHeight": None,
                        "maxHeight": None,
                        "grow": 0,
                        "shrink": 1,
                        "alignSelf": "stretch",
                    },
                    "responsive": [],
                    "content": "等待主管审批",
                    "semantic": "body",
                    "tone": "muted",
                },
            }
        ],
    }
