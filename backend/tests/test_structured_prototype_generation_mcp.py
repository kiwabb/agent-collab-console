from __future__ import annotations

import hashlib
import json

import pytest

from app.adapters.prototype_object_store import canonical_json_bytes
from app.application.structured_prototype_generation_contracts import (
    GeneratedButtonNodeV1,
    GeneratedFormNodeV1,
    GeneratedInputNodeV1,
    GeneratedTableNodeV1,
    GenerationPageEnvelopeV1,
)
from app.application.structured_prototype_generation_mcp import (
    StructuredPrototypeGenerationMcpService,
)


def _tool_call(name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _page_arguments(payload: object) -> dict[str, object]:
    return {
        "payloadJson": json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    }


def _payload() -> dict[str, object]:
    return {
        "contractVersion": 1,
        "pageKey": "purchase-detail",
        "title": "采购申请详情",
        "route": "/purchases/detail",
        "root": {
            "localKey": "detail-root",
            "name": "采购申请详情",
            "type": "Stack",
            "direction": "column",
            "gap": 16,
            "padding": 24,
            "children": [],
        },
    }


def _assert_tool_error(response: dict[str, object] | None) -> None:
    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is True


def _tool_payload(response: dict[str, object] | None) -> dict[str, object]:
    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    text = first["text"]
    assert isinstance(text, str)
    payload = json.loads(text)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.asyncio
async def test_generation_mcp_accepts_one_idempotent_matching_finalization() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")
    call = _tool_call("finalize_prototype_page", _page_arguments(_payload()))

    status, first = await service.handle(token=session.token, payload=call)
    retry_status, retry = await service.handle(token=session.token, payload=call)

    assert status == retry_status == 200
    assert first == retry
    envelope, receipt, process_id = service.submitted_artifact(session)
    assert isinstance(envelope, GenerationPageEnvelopeV1)
    assert envelope.item_id == "item-1"
    assert envelope.payload.page_key == "purchase-detail"
    assert process_id == "process-1"
    assert receipt.request_hash.startswith("sha256:")
    assert receipt.normalized_fields == ()
    assert _tool_payload(first)["normalizedFields"] == []


@pytest.mark.asyncio
async def test_generation_mcp_normalizes_allowlisted_page_fields_before_strict_validation() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["gap"] = "16"
    root["padding"] = "24"
    root["children"] = json.dumps(
        [
            {
                "localKey": "amount-input",
                "name": "采购金额",
                "type": "Input",
                "label": "采购金额",
                "placeholder": "请输入金额",
                "inputType": "number",
                "required": "true",
                "disabled": "false",
            },
            {
                "localKey": "request-form",
                "name": "采购申请表单",
                "type": "Form",
                "formKey": "purchase-form",
                "gap": "12",
                "children": "[]",
            },
            {
                "localKey": "request-table",
                "name": "采购申请列表",
                "type": "Table",
                "columns": json.dumps(
                    [{"key": "status", "label": "状态"}],
                    ensure_ascii=False,
                ),
                "density": "compact",
            },
        ],
        ensure_ascii=False,
    )
    arguments = _page_arguments(payload)
    expected_request_hash = "sha256:" + hashlib.sha256(
        canonical_json_bytes(arguments)
    ).hexdigest()

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", arguments),
    )

    receipt_payload = _tool_payload(response)
    expected_fields = [
        "payload.root.gap",
        "payload.root.padding",
        "payload.root.children",
        "payload.root.children[0].required",
        "payload.root.children[0].disabled",
        "payload.root.children[1].gap",
        "payload.root.children[1].children",
        "payload.root.children[2].columns",
    ]
    assert receipt_payload["requestHash"] == expected_request_hash
    assert receipt_payload["normalizedFields"] == expected_fields
    envelope, receipt, _ = service.submitted_artifact(session)
    assert receipt.request_hash == expected_request_hash
    assert receipt.normalized_fields == tuple(expected_fields)
    assert isinstance(envelope, GenerationPageEnvelopeV1)
    assert envelope.payload.root.gap == 16
    assert envelope.payload.root.padding == 24
    input_node, form_node, table_node = envelope.payload.root.children
    assert isinstance(input_node, GeneratedInputNodeV1)
    assert isinstance(form_node, GeneratedFormNodeV1)
    assert isinstance(table_node, GeneratedTableNodeV1)
    assert input_node.required is True
    assert input_node.disabled is False
    assert form_node.gap == 12
    assert form_node.children == []
    assert table_node.columns[0].key == "status"


@pytest.mark.asyncio
async def test_generation_mcp_normalizes_exact_mcp_array_wrapper_recursively() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["gap"] = "16"
    root["padding"] = "24"
    root["children"] = {
        "item": [
            {
                "localKey": "approve-request",
                "name": "审批通过",
                "type": "Button",
                "label": "审批通过",
                "variant": "primary",
                "disabled": "false",
            }
        ]
    }

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    expected_fields = [
        "payload.root.gap",
        "payload.root.padding",
        "payload.root.children",
        "payload.root.children[0].disabled",
    ]
    assert _tool_payload(response)["normalizedFields"] == expected_fields
    envelope, receipt, _ = service.submitted_artifact(session)
    assert receipt.normalized_fields == tuple(expected_fields)
    assert isinstance(envelope, GenerationPageEnvelopeV1)
    button = envelope.payload.root.children[0]
    assert isinstance(button, GeneratedButtonNodeV1)
    assert button.disabled is False


@pytest.mark.asyncio
async def test_generation_mcp_refuses_array_wrapper_with_extra_fields() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["children"] = {"item": [], "unexpected": True}

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {
        "error": "schema_invalid",
        "issues": [{"path": "root.children", "type": "list_type"}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "expected_path", "expected_type"),
    [
        ("gap", "16px", "root.gap", "int_type"),
        ("children", "[invalid", "root.children", "list_type"),
    ],
)
async def test_generation_mcp_refuses_non_normalizable_page_field_strings(
    field: str,
    value: str,
    expected_path: str,
    expected_type: str,
) -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root[field] = value

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {
        "error": "schema_invalid",
        "issues": [{"path": expected_path, "type": expected_type}],
    }


@pytest.mark.asyncio
async def test_generation_mcp_does_not_synthesize_missing_page_fields() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root.pop("children")

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {
        "error": "schema_invalid",
        "issues": [{"path": "root.children", "type": "missing"}],
    }


@pytest.mark.asyncio
async def test_generation_mcp_refuses_invalid_payload_json() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call(
            "finalize_prototype_page",
            {"payloadJson": "{invalid"},
        ),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {
        "error": "schema_invalid",
        "issues": [{"path": "payloadJson", "type": "json_invalid"}],
    }


@pytest.mark.asyncio
async def test_generation_mcp_refuses_wrong_tool_scope_and_changed_submission() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")

    _, wrong_tool = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_foundation", {"payload": _payload()}),
    )
    _assert_tool_error(wrong_tool)

    valid_call = _tool_call("finalize_prototype_page", _page_arguments(_payload()))
    await service.handle(token=session.token, payload=valid_call)
    changed = _payload()
    changed["title"] = "不同标题"
    _, conflict = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(changed)),
    )
    _assert_tool_error(conflict)


@pytest.mark.asyncio
async def test_generation_mcp_refuses_finalization_before_process_binding() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(_payload())),
    )

    _assert_tool_error(response)


@pytest.mark.asyncio
async def test_generation_mcp_reports_safe_payload_validation_issues() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    service.bind_execution_process(session, "process-1")
    payload = _payload()
    payload.pop("contractVersion")

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    assert response is not None
    assert _tool_payload(response) == {
        "error": "schema_invalid",
        "issues": [{"path": "contractVersion", "type": "missing"}],
    }


def test_generation_mcp_finalization_tool_exposes_strict_payload_schema() -> None:
    tools = StructuredPrototypeGenerationMcpService.descriptor.protocol_tools()
    finalization = next(tool for tool in tools if tool["name"] == "finalize_prototype_page")
    input_schema = finalization["inputSchema"]
    assert isinstance(input_schema, dict)
    properties = input_schema["properties"]
    assert isinstance(properties, dict)
    payload_json_schema = properties["payloadJson"]
    assert isinstance(payload_json_schema, dict)
    payload_schema = input_schema["x-payloadSchema"]
    assert isinstance(payload_schema, dict)

    assert input_schema["required"] == ["payloadJson"]
    assert payload_json_schema["type"] == "string"
    assert payload_schema["additionalProperties"] is False
    assert set(payload_schema["required"]) == set(_payload())
    payload_properties = payload_schema["properties"]
    assert isinstance(payload_properties, dict)
    page_key_schema = payload_properties["pageKey"]
    assert isinstance(page_key_schema, dict)
    assert page_key_schema["pattern"] == "^[a-z][a-z0-9-]{0,63}$"
    assert "$defs" not in payload_schema
    root_schema = payload_properties["root"]
    assert isinstance(root_schema, dict)
    root_reference = root_schema["$ref"]
    assert root_reference == "#/$defs/GeneratedStackNodeV1"
    definitions = input_schema["$defs"]
    assert isinstance(definitions, dict)
    assert "GeneratedStackNodeV1" in definitions
