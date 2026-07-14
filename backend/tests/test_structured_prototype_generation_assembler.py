from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID, uuid5

import pytest
from test_structured_prototype_generation_contracts import (
    blueprint_payload,
    foundation_payload,
    page_payload,
)

from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.application.structured_prototype_contracts import (
    StackNodeV1,
    document_hash,
    document_payload,
)
from app.application.structured_prototype_generation_assembler import (
    PROCUREMENT_ENTITY_NAMESPACE,
    StructuredPrototypeGenerationAssemblyError,
    assemble_procurement_candidate,
    procurement_page_skeleton,
)
from app.application.structured_prototype_generation_contracts import (
    GeneratedPageV1,
    GenerationBlueprintV1,
    GenerationFoundationV1,
)


def _id(seed: str) -> str:
    return str(uuid5(PROCUREMENT_ENTITY_NAMESPACE, seed))


def _complete_blueprint_payload() -> dict[str, object]:
    payload = blueprint_payload()
    flows = payload["flowIntents"]
    assert isinstance(flows, list)
    flows.extend(
        [
            {
                "key": "select-request",
                "sourcePageKey": "purchase-list",
                "sourceNodeKey": "request-table",
                "event": "rowActivated",
                "targetPageKey": "purchase-detail",
            },
            {
                "key": "approve-request",
                "sourcePageKey": "purchase-detail",
                "sourceNodeKey": "approve-request",
                "event": "click",
                "targetPageKey": "purchase-detail",
            },
        ]
    )
    return payload


def _list_page_payload() -> dict[str, object]:
    return {
        "contractVersion": 1,
        "pageKey": "purchase-list",
        "title": "采购申请列表",
        "route": "/purchases",
        "root": {
            "localKey": "list-root",
            "name": "采购申请列表页面",
            "type": "Stack",
            "direction": "column",
            "gap": 16,
            "padding": 24,
            "children": [
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
            ],
        },
    }


def _create_page_payload() -> dict[str, object]:
    payload = page_payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root_children = root["children"]
    assert isinstance(root_children, list)
    form = root_children[0]
    assert isinstance(form, dict)
    form_children = form["children"]
    assert isinstance(form_children, list)
    form_children.insert(
        1,
        {
            "localKey": "amount-input",
            "name": "采购金额",
            "type": "Input",
            "label": "采购金额",
            "placeholder": "请输入整数金额",
            "inputType": "number",
            "required": True,
        },
    )
    return payload


def _detail_page_payload() -> dict[str, object]:
    return {
        "contractVersion": 1,
        "pageKey": "purchase-detail",
        "title": "采购申请详情",
        "route": "/purchases/detail",
        "root": {
            "localKey": "detail-root",
            "name": "采购申请详情页面",
            "type": "Stack",
            "direction": "column",
            "gap": 16,
            "padding": 24,
            "children": [
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
            ],
        },
    }


def _artifacts() -> tuple[
    GenerationBlueprintV1,
    GenerationFoundationV1,
    tuple[GeneratedPageV1, ...],
]:
    blueprint = GenerationBlueprintV1.model_validate(_complete_blueprint_payload(), strict=True)
    foundation = GenerationFoundationV1.model_validate(foundation_payload(), strict=True)
    pages = tuple(
        GeneratedPageV1.model_validate(payload, strict=True)
        for payload in (_list_page_payload(), _create_page_payload(), _detail_page_payload())
    )
    return blueprint, foundation, pages


def test_procurement_page_skeletons_are_strict_valid_page_payloads() -> None:
    blueprint, _, _ = _artifacts()

    generated = [
        GeneratedPageV1.model_validate(
            procurement_page_skeleton(page.page_key, page.title, page.route),
            strict=True,
        )
        for page in blueprint.pages
    ]

    assert [page.page_key for page in generated] == [
        "purchase-list",
        "purchase-create",
        "purchase-detail",
    ]


def test_assembler_uses_navigation_targets_instead_of_model_local_keys() -> None:
    blueprint, foundation, pages = _artifacts()
    renamed_navigation = [
        item.model_copy(update={"key": f"nav-{item.key}"}) for item in blueprint.navigation
    ]

    document = assemble_procurement_candidate(
        document_id=_id("navigation-local-keys"),
        blueprint=blueprint.model_copy(update={"navigation": renamed_navigation}),
        foundation=foundation,
        pages=pages,
    )

    assert len(document.navigation.items) == 3


def test_assembler_is_deterministic_and_matches_studio_semantic_ids() -> None:
    blueprint, foundation, pages = _artifacts()
    document_id = str(uuid5(UUID("40a604ef-4769-5b60-9562-9cd0d9bfcbbd"), "candidate-1"))

    first = assemble_procurement_candidate(
        document_id=document_id,
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )
    replay = assemble_procurement_candidate(
        document_id=document_id,
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )

    assert document_hash(first) == document_hash(replay)
    assert first.pages[0].id == "cdb0bb26-ce9d-5a2c-9265-c048aa1da81f"
    list_root = first.pages[0].root
    detail_root = first.pages[2].root
    assert isinstance(list_root, StackNodeV1)
    assert isinstance(detail_root, StackNodeV1)
    assert list_root.children[1].id == "cf8fe42a-7d26-5cdf-9ffa-6cb6901ee29d"
    assert detail_root.children[3].id == "c62ff92a-40b4-5d48-a18e-776326e5e0ae"
    assert [rule.key for rule in first.runtime.rules] == [
        "submit-request",
        "select-request",
        "approve-request",
    ]


def test_assembler_refuses_a_page_missing_required_semantic_node() -> None:
    blueprint, foundation, pages = _artifacts()
    invalid_payload = deepcopy(_detail_page_payload())
    root = invalid_payload["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    children.pop()
    invalid_detail = GeneratedPageV1.model_validate(invalid_payload, strict=True)

    with pytest.raises(StructuredPrototypeGenerationAssemblyError) as error:
        assemble_procurement_candidate(
            document_id=_id("candidate-missing-node"),
            blueprint=blueprint,
            foundation=foundation,
            pages=(pages[0], pages[1], invalid_detail),
        )
    assert error.value.code == "generation_semantic_invalid"


@pytest.mark.asyncio
async def test_assembled_candidate_passes_procurement_runtime_scenario_and_replay() -> None:
    blueprint, foundation, pages = _artifacts()
    document = assemble_procurement_candidate(
        document_id=_id("candidate-runtime-validation"),
        blueprint=blueprint,
        foundation=foundation,
        pages=pages,
    )
    definition = document.runtime.model_dump(mode="json", by_alias=True)
    worker = PrototypeRuntimeWorker()
    initial = await worker.initialize_state(
        request_id="generation-candidate-initialize",
        definition=definition,
        scenario_id=_id("scenario-happy-path"),
        session_id="generation-candidate-validation",
    )
    batches = [
        {
            "clientEventId": "submit-request",
            "expectedSequenceNo": 0,
            "events": [
                {
                    "kind": "fieldValueCommitted",
                    "nodeId": _id("input-title"),
                    "formId": _id("form-create"),
                    "fieldId": _id("form-field-title"),
                    "value": {"type": "string", "value": "研发笔记本电脑"},
                },
                {
                    "kind": "fieldValueCommitted",
                    "nodeId": _id("input-amount"),
                    "formId": _id("form-create"),
                    "fieldId": _id("form-field-amount"),
                    "value": {"type": "integer", "value": 12500},
                },
                {
                    "kind": "nodeActivated",
                    "nodeId": _id("button-submit"),
                    "event": "submit",
                },
            ],
        },
        {
            "clientEventId": "switch-manager",
            "expectedSequenceNo": 1,
            "events": [{"kind": "switchSimulatedRole", "roleId": _id("role-manager")}],
        },
        {
            "clientEventId": "approve-request",
            "expectedSequenceNo": 2,
            "events": [
                {
                    "kind": "nodeActivated",
                    "nodeId": _id("button-approve"),
                    "event": "click",
                }
            ],
        },
    ]

    replayed = await worker.replay_event_batches(
        request_id="generation-candidate-replay",
        definition=definition,
        state_json=initial.state_json,
        batches=batches,
    )
    final_state = json.loads(replayed.final.state_json)
    final_view_model = json.loads(replayed.final.view_model_json)

    assert [transition.outcome for transition in replayed.transitions] == [
        "applied",
        "applied",
        "applied",
    ]
    assert final_state["sequenceNo"] == 3
    request_set = final_state["entitySets"][0]
    status_field = next(
        field
        for field in request_set["entities"][0]["fields"]
        if field["fieldId"] == _id("schema-field-status")
    )
    assert status_field["value"] == {"type": "enum", "value": "approved"}
    assert replayed.final.state_hash.startswith("sha256:")
    assert replayed.final.view_model_hash.startswith("sha256:")
    detail_status = next(
        node for node in final_view_model["nodes"] if node["nodeId"] == _id("detail-status")
    )
    assert detail_status["properties"] == [
        {"target": "textContent", "value": {"type": "enum", "value": "approved"}}
    ]
    assert document_payload(document)["runtime"] == definition
