from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from test_structured_prototype_generation_contracts import (
    blueprint_payload,
    foundation_payload,
)

import app.application.structured_prototype_generation_mcp as generation_mcp_module
from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.prototype_object_store import canonical_json_bytes
from app.application import audit
from app.application.audit import recorders as audit_recorders
from app.application.audit.writer import AuditLogger
from app.application.structured_prototype_generation_contracts import (
    GeneratedButtonNodeV1,
    GeneratedFormNodeV1,
    GeneratedGridNodeV1,
    GeneratedInputNodeV1,
    GeneratedTableNodeV1,
    GenerationFoundationEnvelopeV1,
    GenerationPageEnvelopeV1,
    GenerationTaskKind,
)
from app.application.structured_prototype_generation_mcp import (
    GENERATION_MCP_PAYLOAD_MAX_BYTES,
    GenerationMcpSession,
    GenerationMcpSubmissionEvidence,
    StructuredPrototypeGenerationMcpError,
    StructuredPrototypeGenerationMcpService,
)


def _tool_call(name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _bind_execution(
    service: StructuredPrototypeGenerationMcpService,
    session: GenerationMcpSession,
    root: Path | None = None,
) -> None:
    service.bind_repository_root(
        session,
        task_id=session.task_id,
        worktree_root=root or Path(__file__).parent,
    )
    service.bind_execution_process(session, "process-1")
    service.bind_wire_input(
        session,
        task_id=session.task_id,
        execution_process_id="process-1",
        wire_input_hash="sha256:" + "a" * 64,
    )


def _open_discovery_session(
    service: StructuredPrototypeGenerationMcpService,
    root: Path,
) -> GenerationMcpSession:
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
    )
    _bind_execution(service, session, root)
    return session


def _open_blueprint_discovery_session(
    service: StructuredPrototypeGenerationMcpService,
    root: Path,
) -> GenerationMcpSession:
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_blueprint",
        context_object_hash="sha256:" + "b" * 64,
    )
    _bind_execution(service, session, root)
    return session


def _blueprint_discovery_calls() -> tuple[tuple[str, dict[str, object]], ...]:
    return (
        ("list_project_files", {"pattern": "**/*.ts"}),
        ("search_project_text", {"query": "dashboardRoute"}),
        ("read_project_file", {"path": "routes.ts"}),
    )


async def _assert_successful_tool_call(
    service: StructuredPrototypeGenerationMcpService,
    session: GenerationMcpSession,
    name: str,
    arguments: dict[str, object],
) -> None:
    _, response = await service.handle(
        token=session.token,
        payload=_tool_call(name, arguments),
    )
    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is False


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
                }
            ],
        },
        "formBindings": [],
        "viewBindings": [],
        "behaviorBindings": [],
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
    _bind_execution(service, session)
    call = _tool_call("finalize_prototype_page", _page_arguments(_payload()))

    status, first = await service.handle(token=session.token, payload=call)
    retry_status, retry = await service.handle(token=session.token, payload=call)

    assert status == retry_status == 200
    assert first == retry
    envelope, receipt, process_id = service.submitted_artifact(session)
    assert isinstance(envelope, GenerationPageEnvelopeV1)
    assert envelope.item_id == "item-1"
    assert envelope.payload.page_key == "users"
    assert process_id == "process-1"
    assert receipt.request_hash.startswith("sha256:")
    assert receipt.normalized_fields == ()
    assert _tool_payload(first)["normalizedFields"] == []


@pytest.mark.asyncio
async def test_generation_mcp_persists_submission_evidence_before_accepting_state() -> None:
    service = StructuredPrototypeGenerationMcpService()
    captured: list[GenerationMcpSubmissionEvidence] = []

    async def accept_submission(evidence: GenerationMcpSubmissionEvidence) -> None:
        with pytest.raises(StructuredPrototypeGenerationMcpError, match="did not finalize"):
            service.submitted_artifact(session)
        captured.append(evidence)

    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
        submission_accepted_callback=accept_submission,
    )
    _bind_execution(service, session)
    arguments = _page_arguments(_payload())
    expected_raw_hash = "sha256:" + hashlib.sha256(canonical_json_bytes(arguments)).hexdigest()

    status, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", arguments),
    )

    assert status == 200
    assert response is not None
    assert len(captured) == 1
    evidence = captured[0]
    receipt = evidence.receipt
    assert evidence.project_id == "project-1"
    assert evidence.execution_process_id == "process-1"
    assert receipt.request_hash == expected_raw_hash
    assert receipt.wire_input_hash == "sha256:" + "a" * 64
    assert receipt.scope_fingerprint.startswith("sha256:")
    assert receipt.envelope_hash.startswith("sha256:")
    assert receipt.envelope_size > 0
    assert receipt.path_contained is True
    assert receipt.resolved_path == receipt.repository_root
    assert (
        json.loads(json.dumps(receipt.to_dict()))["scopeFingerprint"] == receipt.scope_fingerprint
    )
    accepted_envelope, accepted_receipt, process_id = service.submitted_artifact(session)
    assert accepted_envelope.item_id == "item-1"
    expected_normalized_hash = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {"payloadJson": accepted_envelope.payload.model_dump(mode="json", by_alias=True)}
            )
        ).hexdigest()
    )
    assert receipt.normalized_request_hash == expected_normalized_hash
    assert accepted_receipt == receipt
    assert process_id == "process-1"
    payload = _tool_payload(response)
    assert payload["wireInputHash"] == receipt.wire_input_hash
    assert payload["pathContained"] is True


@pytest.mark.asyncio
async def test_generation_mcp_callback_failure_refuses_submission_without_session_state() -> None:
    service = StructuredPrototypeGenerationMcpService()
    calls = 0

    async def reject_submission(_: GenerationMcpSubmissionEvidence) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("operation event unavailable")

    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "b" * 64,
        submission_accepted_callback=reject_submission,
    )
    _bind_execution(service, session)
    call = _tool_call("finalize_prototype_page", _page_arguments(_payload()))

    status, response = await service.handle(token=session.token, payload=call)

    assert status == 200
    assert _tool_payload(response) == {"error": "submission_evidence_unavailable"}
    with pytest.raises(StructuredPrototypeGenerationMcpError, match="did not finalize"):
        service.submitted_artifact(session)
    retry_status, retry = await service.handle(token=session.token, payload=call)
    assert retry_status == 200
    assert _tool_payload(retry) == {"error": "submission_evidence_unavailable"}
    assert calls == 2


@pytest.mark.asyncio
async def test_generation_mcp_refuses_empty_generated_page_root() -> None:
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
    _bind_execution(service, session)
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["children"] = []

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    result = _tool_payload(response)
    assert result["error"] == "schema_invalid"
    assert result["issues"] == [{"path": "$", "type": "value_error"}]


@pytest.mark.asyncio
async def test_generation_mcp_accepts_foundation_payload_json_and_hashes_raw_arguments() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_foundation",
        context_object_hash="sha256:" + "b" * 64,
    )
    _bind_execution(service, session)
    arguments = _page_arguments(foundation_payload())
    expected_request_hash = "sha256:" + hashlib.sha256(canonical_json_bytes(arguments)).hexdigest()

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_foundation", arguments),
    )

    assert _tool_payload(response)["requestHash"] == expected_request_hash
    envelope, receipt, process_id = service.submitted_artifact(session)
    assert isinstance(envelope, GenerationFoundationEnvelopeV1)
    assert envelope.payload.shared_shell.title == "Northstar 管理后台"
    assert receipt.request_hash == expected_request_hash
    assert receipt.normalized_fields == ()
    assert process_id == "process-1"


@pytest.mark.asyncio
async def test_generation_mcp_refuses_css_shorthand_foundation_spacing_token() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_foundation",
        context_object_hash="sha256:" + "b" * 64,
    )
    _bind_execution(service, session)
    payload = foundation_payload()
    spacing = payload["spacing"]
    assert isinstance(spacing, list)
    token = spacing[0]
    assert isinstance(token, dict)
    token["value"] = "34px 32px 48px"

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_foundation", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    result = _tool_payload(response)
    assert result["error"] == "schema_invalid"
    issues = result["issues"]
    assert isinstance(issues, list)
    assert any(
        isinstance(issue, dict)
        and issue.get("path") == "spacing.0.value"
        and issue.get("type") == "string_pattern_mismatch"
        for issue in issues
    )


@pytest.mark.asyncio
async def test_generation_mcp_refuses_legacy_foundation_object_argument() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_foundation",
        context_object_hash="sha256:" + "b" * 64,
    )
    _bind_execution(service, session)

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call(
            "finalize_prototype_foundation",
            {"payload": foundation_payload()},
        ),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {"error": "schema_invalid"}
    with pytest.raises(StructuredPrototypeGenerationMcpError):
        service.submitted_artifact(session)


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
    _bind_execution(service, session)
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["gap"] = "16"
    root["padding"] = "24"
    root["children"] = json.dumps(
        [
            {
                "localKey": "email-input",
                "name": "用户邮箱",
                "type": "Input",
                "label": "用户邮箱",
                "placeholder": "请输入邮箱",
                "inputType": "email",
                "required": "true",
                "disabled": "false",
            },
            {
                "localKey": "user-filter-form",
                "name": "用户筛选表单",
                "type": "Form",
                "formKey": "user-filter",
                "gap": "12",
                "children": "[]",
            },
            {
                "localKey": "users-table",
                "name": "用户列表",
                "type": "Table",
                "columns": json.dumps(
                    [{"key": "status", "label": "状态"}],
                    ensure_ascii=False,
                ),
                "rows": [],
                "density": "compact",
            },
            {
                "localKey": "metric-grid",
                "name": "指标网格",
                "type": "Grid",
                "columns": "1",
                "gap": "16",
                "padding": "0",
                "columnOverrides": json.dumps(
                    [
                        {"minWidth": "768", "columns": "2"},
                        {"minWidth": "1200", "columns": "4"},
                    ]
                ),
                "children": "[]",
            },
        ],
        ensure_ascii=False,
    )
    arguments = _page_arguments(payload)
    expected_request_hash = "sha256:" + hashlib.sha256(canonical_json_bytes(arguments)).hexdigest()

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
        "payload.root.children[3].columns",
        "payload.root.children[3].gap",
        "payload.root.children[3].padding",
        "payload.root.children[3].columnOverrides",
        "payload.root.children[3].columnOverrides[0].minWidth",
        "payload.root.children[3].columnOverrides[0].columns",
        "payload.root.children[3].columnOverrides[1].minWidth",
        "payload.root.children[3].columnOverrides[1].columns",
        "payload.root.children[3].children",
    ]
    assert receipt_payload["requestHash"] == expected_request_hash
    assert receipt_payload["normalizedFields"] == expected_fields
    envelope, receipt, _ = service.submitted_artifact(session)
    assert receipt.request_hash == expected_request_hash
    assert receipt.normalized_fields == tuple(expected_fields)
    assert isinstance(envelope, GenerationPageEnvelopeV1)
    assert envelope.payload.root.gap == 16
    assert envelope.payload.root.padding == 24
    input_node, form_node, table_node, grid_node = envelope.payload.root.children
    assert isinstance(input_node, GeneratedInputNodeV1)
    assert isinstance(form_node, GeneratedFormNodeV1)
    assert isinstance(table_node, GeneratedTableNodeV1)
    assert isinstance(grid_node, GeneratedGridNodeV1)
    assert input_node.required is True
    assert input_node.disabled is False
    assert form_node.gap == 12
    assert form_node.children == []
    assert table_node.columns[0].key == "status"
    assert table_node.rows == []
    assert grid_node.columns == 1
    assert [(item.min_width, item.columns) for item in grid_node.column_overrides] == [
        (768, 2),
        (1200, 4),
    ]


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
    _bind_execution(service, session)
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["gap"] = "16"
    root["padding"] = "24"
    root["children"] = {
        "item": [
            {
                "localKey": "open-orders",
                "name": "查看订单",
                "type": "Button",
                "label": "查看订单",
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
    _bind_execution(service, session)
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
    _bind_execution(service, session)
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
    _bind_execution(service, session)
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
@pytest.mark.parametrize(
    ("task_kind", "tool_name"),
    [
        ("generation_foundation", "finalize_prototype_foundation"),
        ("generation_page", "finalize_prototype_page"),
    ],
)
async def test_generation_mcp_refuses_invalid_payload_json(
    task_kind: GenerationTaskKind,
    tool_name: str,
) -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind=task_kind,
        context_object_hash="sha256:" + "b" * 64,
    )
    _bind_execution(service, session)

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call(
            tool_name,
            {"payloadJson": "{invalid"},
        ),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {
        "error": "schema_invalid",
        "issues": [{"path": "payloadJson", "type": "json_invalid"}],
    }


@pytest.mark.asyncio
async def test_generation_mcp_refuses_corrupted_foundation_without_normalization() -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind="generation_foundation",
        context_object_hash="sha256:" + "b" * 64,
    )
    _bind_execution(service, session)
    payload = foundation_payload()
    payload["sharedShell"] = ""

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_foundation", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {
        "error": "schema_invalid",
        "issues": [{"path": "sharedShell", "type": "model_attributes_type"}],
    }
    with pytest.raises(
        StructuredPrototypeGenerationMcpError,
        match="did not finalize its artifact",
    ):
        service.submitted_artifact(session)


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
    _bind_execution(service, session)

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
    _bind_execution(service, session)
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensitive_field_name",
    ["sk-capability-secret-123", "customer-email-alice-example-com"],
)
async def test_generation_mcp_normalizes_model_controlled_extra_field_paths(
    sensitive_field_name: str,
    monkeypatch,
) -> None:
    recorded: list[dict[str, object]] = []

    def capture(**fields: object) -> None:
        recorded.append(fields)

    monkeypatch.setattr(audit, "record_mcp_call", capture)
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
    _bind_execution(service, session)
    payload = _payload()
    payload[sensitive_field_name] = "private-value"

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {
        "error": "schema_invalid",
        "issues": [{"path": "__extra__", "type": "extra_forbidden"}],
    }
    assert len(recorded) == 1
    assert recorded[0]["failure_evidence"] == audit.McpCallFailureEvidence(
        code="schema_invalid",
        issues=(
            audit.McpValidationIssueEvidence(
                path="__extra__",
                issue_type="extra_forbidden",
            ),
        ),
    )
    assert sensitive_field_name not in repr(recorded)


@pytest.mark.asyncio
async def test_generation_mcp_persists_root_semantic_validation_failure(
    tmp_path,
    monkeypatch,
) -> None:
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store._ensure_db()
    logger = AuditLogger()
    logger.set_store(store)
    logger.set_loop(asyncio.get_running_loop())
    monkeypatch.setattr(audit_recorders, "default_sink", lambda: logger)
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
    _bind_execution(service, session)
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["children"] = [
        {
            "localKey": root["localKey"],
            "name": "重复节点",
            "type": "Text",
            "content": "重复节点",
            "semantic": "body",
            "tone": "default",
        }
    ]

    try:
        _, response = await service.handle(
            token=session.token,
            payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
        )
        await logger.drain()

        _assert_tool_error(response)
        assert _tool_payload(response) == {
            "error": "schema_invalid",
            "issues": [{"path": "$", "type": "value_error"}],
        }
        rows = await store.list_audit_logs(limit=10)
        assert len(rows) == 1
        audit_payload = json.loads(rows[0].payload_json)
        assert audit_payload["failure"] == {
            "code": "schema_invalid",
            "issues": [{"path": "$", "type": "value_error"}],
        }
    finally:
        await logger.shutdown()
        await store.close()


@pytest.mark.asyncio
async def test_generation_mcp_passes_only_safe_failure_evidence_to_audit(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []

    def capture(**fields: object) -> None:
        recorded.append(fields)

    monkeypatch.setattr(audit, "record_mcp_call", capture)
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
    _bind_execution(service, session)
    sensitive_payload = "private-business-value-capability-token-123"
    payload = _payload()
    payload["title"] = sensitive_payload
    payload.pop("contractVersion")

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    _assert_tool_error(response)
    assert len(recorded) == 1
    call = recorded[0]
    assert call["is_error"] is True
    assert call["failure_evidence"] == audit.McpCallFailureEvidence(
        code="schema_invalid",
        issues=(
            audit.McpValidationIssueEvidence(
                path="contractVersion",
                issue_type="missing",
            ),
        ),
    )
    captured = repr(call)
    assert sensitive_payload not in captured
    assert session.token not in captured
    assert "arguments" not in call
    assert "payload" not in call


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
    grid_schema = definitions["GeneratedGridNodeV1"]
    assert isinstance(grid_schema, dict)
    grid_properties = grid_schema["properties"]
    assert isinstance(grid_properties, dict)
    assert "columnOverrides" in grid_properties
    assert "column_overrides" not in grid_properties
    table_schema = definitions["GeneratedTableNodeV1"]
    assert isinstance(table_schema, dict)
    assert "rows" in table_schema["required"]
    table_properties = table_schema["properties"]
    assert isinstance(table_properties, dict)
    rows_schema = table_properties["rows"]
    assert isinstance(rows_schema, dict)
    assert rows_schema["type"] == "array"
    assert rows_schema["maxItems"] == 200
    assert "native JSON array" in rows_schema["description"]


def test_generation_mcp_foundation_uses_bounded_json_and_blueprint_stays_object() -> None:
    tools = StructuredPrototypeGenerationMcpService.descriptor.protocol_tools()
    foundation = next(tool for tool in tools if tool["name"] == "finalize_prototype_foundation")
    foundation_schema = foundation["inputSchema"]
    assert isinstance(foundation_schema, dict)
    foundation_properties = foundation_schema["properties"]
    assert isinstance(foundation_properties, dict)
    payload_json_schema = foundation_properties["payloadJson"]
    assert isinstance(payload_json_schema, dict)
    payload_schema = foundation_schema["x-payloadSchema"]
    assert isinstance(payload_schema, dict)

    assert foundation_schema["required"] == ["payloadJson"]
    assert payload_json_schema["type"] == "string"
    assert payload_json_schema["maxLength"] == GENERATION_MCP_PAYLOAD_MAX_BYTES
    assert set(payload_schema["required"]) == set(foundation_payload())
    assert "GenerationSidebarShellV3" in foundation_schema["$defs"]

    blueprint = next(tool for tool in tools if tool["name"] == "finalize_prototype_blueprint")
    blueprint_schema = blueprint["inputSchema"]
    assert isinstance(blueprint_schema, dict)
    assert blueprint_schema["required"] == ["payload"]
    blueprint_properties = blueprint_schema["properties"]
    assert isinstance(blueprint_properties, dict)
    assert "payload" in blueprint_properties
    assert "payloadJson" not in blueprint_properties


def test_generation_mcp_discovery_descriptors_are_read_only_and_bounded() -> None:
    by_name = {tool.id: tool for tool in StructuredPrototypeGenerationMcpService.descriptor.tools}

    for name in ("list_project_files", "search_project_text", "read_project_file"):
        descriptor = by_name[name]
        assert descriptor.risk_level == "read"
        schema = descriptor.input_schema
        assert schema["additionalProperties"] is False

    list_properties = by_name["list_project_files"].input_schema["properties"]
    search_properties = by_name["search_project_text"].input_schema["properties"]
    read_properties = by_name["read_project_file"].input_schema["properties"]
    assert isinstance(list_properties, dict)
    assert isinstance(search_properties, dict)
    assert isinstance(read_properties, dict)
    assert list_properties["limit"]["maximum"] == 500
    assert search_properties["limit"]["maximum"] == 100
    assert read_properties["lineCount"]["maximum"] == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_rows",
    [json.dumps([], separators=(",", ":")), {"item": []}],
)
async def test_generation_mcp_requires_native_table_rows_array(
    invalid_rows: object,
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
    _bind_execution(service, session)
    payload = _payload()
    root = payload["root"]
    assert isinstance(root, dict)
    root["children"] = [
        {
            "localKey": "users-table",
            "name": "用户列表",
            "type": "Table",
            "columns": [{"key": "status", "label": "状态"}],
            "rows": invalid_rows,
            "density": "compact",
        }
    ]

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(payload)),
    )

    result = _tool_payload(response)
    assert result["error"] == "schema_invalid"
    issues = result["issues"]
    assert isinstance(issues, list)
    assert any(
        isinstance(issue, dict)
        and isinstance(issue.get("path"), str)
        and issue["path"].endswith("rows")
        for issue in issues
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_kind", "allowed_tool"),
    [
        ("generation_blueprint", "finalize_prototype_blueprint"),
        ("generation_foundation", "finalize_prototype_foundation"),
        ("generation_page", "finalize_prototype_page"),
    ],
)
async def test_generation_mcp_lists_only_the_session_finalization_tool(
    task_kind: GenerationTaskKind,
    allowed_tool: str,
) -> None:
    service = StructuredPrototypeGenerationMcpService()
    session = service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="task-1",
        task_kind=task_kind,
        context_object_hash="sha256:" + "b" * 64,
    )

    status, response = await service.handle(
        token=session.token,
        payload={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )

    assert status == 200
    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    tools = result["tools"]
    assert isinstance(tools, list)
    assert [tool["name"] for tool in tools if isinstance(tool, dict)] == [
        "get_generation_submission_context",
        "list_project_files",
        "search_project_text",
        "read_project_file",
        allowed_tool,
    ]


@pytest.mark.asyncio
async def test_generation_mcp_lists_searches_and_reads_bound_repository_deterministically(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "app.ts").write_text(
        "const exact = 'user.*';\nconst label = 'Users';\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "routes.ts").write_text(
        "export const route = '/users';\nconst second = 'user.*';\n",
        encoding="utf-8",
    )
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    _, first_list = await service.handle(
        token=session.token,
        payload=_tool_call("list_project_files", {"pattern": "**/*.ts", "limit": 1}),
    )
    _, second_list = await service.handle(
        token=session.token,
        payload=_tool_call("list_project_files", {"pattern": "**/*.ts", "limit": 1}),
    )
    listed = _tool_payload(first_list)

    assert listed["files"] == [
        {"path": "app.ts", "sizeBytes": (tmp_path / "app.ts").stat().st_size}
    ]
    assert listed["matchedCount"] == 2
    assert listed["truncated"] is True
    assert listed["truncationReasons"] == ["result_limit"]
    assert listed["resultHash"] == _tool_payload(second_list)["resultHash"]

    _, search_response = await service.handle(
        token=session.token,
        payload=_tool_call(
            "search_project_text",
            {
                "query": "user.*",
                "filePattern": "**/*.ts",
                "caseSensitive": True,
                "limit": 1,
            },
        ),
    )
    searched = _tool_payload(search_response)
    assert searched["matchedCount"] == 2
    assert searched["returnedCount"] == 1
    assert searched["truncationReasons"] == ["result_limit"]
    matches = searched["matches"]
    assert isinstance(matches, list)
    assert matches[0]["path"] == "app.ts"
    assert matches[0]["line"] == 1

    _, read_response = await service.handle(
        token=session.token,
        payload=_tool_call(
            "read_project_file",
            {"path": "src/routes.ts", "startLine": 2, "lineCount": 1},
        ),
    )
    read = _tool_payload(read_response)
    assert read["path"] == "src/routes.ts"
    assert read["lines"] == [
        {"line": 2, "text": "const second = 'user.*';", "textTruncated": False}
    ]
    assert read["eof"] is True
    assert len(canonical_json_bytes(read)) <= 64 * 1024


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_path", ["../secret.txt", "/etc/passwd", "src\\file.ts"])
async def test_generation_mcp_refuses_repository_path_escape(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    (tmp_path / "safe.txt").write_text("safe\n", encoding="utf-8")
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("read_project_file", {"path": unsafe_path}),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {"error": "repository_scope_violation"}


@pytest.mark.asyncio
async def test_generation_mcp_refuses_symlink_oversize_and_binary_reads(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)
    (tmp_path / "large.txt").write_text("x" * 100_001, encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"text\x00binary")
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    expected = {
        "linked.txt": "repository_scope_violation",
        "large.txt": "file_size_limit",
        "binary.dat": "binary_file_refused",
    }
    for path, error_code in expected.items():
        _, response = await service.handle(
            token=session.token,
            payload=_tool_call("read_project_file", {"path": path}),
        )
        _assert_tool_error(response)
        assert _tool_payload(response) == {"error": error_code}

    _, list_response = await service.handle(
        token=session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    _assert_tool_error(list_response)
    assert _tool_payload(list_response) == {"error": "repository_scope_violation"}


def test_generation_mcp_requires_repository_binding_before_process() -> None:
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

    with pytest.raises(StructuredPrototypeGenerationMcpError) as missing:
        service.bind_execution_process(session, "process-1")
    assert missing.value.code == "repository_scope_missing"

    with pytest.raises(StructuredPrototypeGenerationMcpError) as mismatch:
        service.bind_repository_root(
            session,
            task_id="other-task",
            worktree_root=Path(__file__).parent,
        )
    assert mismatch.value.code == "repository_scope_violation"


@pytest.mark.asyncio
async def test_generation_mcp_refuses_discovery_after_finalization(tmp_path: Path) -> None:
    (tmp_path / "app.ts").write_text("export const app = true;\n", encoding="utf-8")
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)
    await service.handle(
        token=session.token,
        payload=_tool_call("finalize_prototype_page", _page_arguments(_payload())),
    )

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {"error": "submission_already_finalized"}


@pytest.mark.asyncio
async def test_generation_mcp_close_waits_for_in_flight_repository_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "app.ts").write_text("export const app = true;\n", encoding="utf-8")
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)
    started = threading.Event()
    release = threading.Event()
    original = generation_mcp_module._list_project_files

    def slow_list(*args: Any, **kwargs: Any) -> Any:
        started.set()
        assert release.wait(timeout=2)
        return original(*args, **kwargs)

    monkeypatch.setattr(generation_mcp_module, "_list_project_files", slow_list)
    handle_task = asyncio.create_task(
        service.handle(
            token=session.token,
            payload=_tool_call("list_project_files", {"pattern": "**"}),
        )
    )
    assert await asyncio.to_thread(started.wait, 1)

    handle_task.cancel()
    close_task = asyncio.create_task(service.close_session(session))
    await asyncio.sleep(0)
    assert handle_task.done() is False
    assert close_task.done() is False

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await handle_task
    await close_task
    assert service.active_session_count() == 0


@pytest.mark.asyncio
async def test_cancelled_repository_scan_consumes_quota_and_records_safe_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "app.ts").write_text("export const app = true;\n", encoding="utf-8")
    monkeypatch.setattr(
        generation_mcp_module,
        "GENERATION_DISCOVERY_SESSION_MAX_SCAN_FILES",
        1,
    )
    recorded: list[dict[str, object]] = []

    def record_call(**kwargs: object) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(generation_mcp_module.audit, "record_mcp_call", record_call)
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)
    started = threading.Event()
    release = threading.Event()
    original = generation_mcp_module._list_project_files

    def slow_list(*args: Any, **kwargs: Any) -> Any:
        started.set()
        assert release.wait(timeout=2)
        return original(*args, **kwargs)

    monkeypatch.setattr(generation_mcp_module, "_list_project_files", slow_list)
    handle_task = asyncio.create_task(
        service.handle(
            token=session.token,
            payload=_tool_call("list_project_files", {"pattern": "**"}),
        )
    )
    assert await asyncio.to_thread(started.wait, 1)
    handle_task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await handle_task

    assert len(recorded) == 1
    cancelled_audit = recorded[0]
    assert cancelled_audit["tool_id"] == "list_project_files"
    assert cancelled_audit["failure_evidence"] == audit.McpCallFailureEvidence(
        code="repository_call_cancelled",
        issues=(),
    )
    assert set(cancelled_audit).isdisjoint({"arguments", "query", "path", "result", "token"})

    _, retry = await service.handle(
        token=session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    _assert_tool_error(retry)
    assert _tool_payload(retry) == {"error": "repository_scan_quota_exceeded"}


@pytest.mark.asyncio
async def test_repository_scan_budget_is_hard_capped_before_file_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "eleven.txt").write_text("12345678901", encoding="utf-8")
    monkeypatch.setattr(
        generation_mcp_module,
        "GENERATION_DISCOVERY_SESSION_MAX_SCAN_BYTES",
        10,
    )
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("read_project_file", {"path": "eleven.txt"}),
    )
    _assert_tool_error(response)
    assert _tool_payload(response) == {"error": "repository_scan_quota_exceeded"}

    _, retry = await service.handle(
        token=session.token,
        payload=_tool_call("read_project_file", {"path": "eleven.txt"}),
    )
    _assert_tool_error(retry)
    assert _tool_payload(retry) == {"error": "repository_scan_quota_exceeded"}


@pytest.mark.asyncio
async def test_generation_mcp_direct_read_and_listing_share_excluded_path_policy(
    tmp_path: Path,
) -> None:
    (tmp_path / ".GIT").write_text("gitdir: /private/checkout\n", encoding="utf-8")
    for directory in (".AGENT-COLLAB", "NODE_MODULES", "PROTOTYPES"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "secret.txt").write_text("secret\n", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("visible\n", encoding="utf-8")
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    _, list_response = await service.handle(
        token=session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    assert _tool_payload(list_response)["files"] == [{"path": "visible.txt", "sizeBytes": 8}]

    for path in (
        ".GIT",
        ".AGENT-COLLAB/secret.txt",
        "NODE_MODULES/secret.txt",
        "PROTOTYPES/secret.txt",
    ):
        _, read_response = await service.handle(
            token=session.token,
            payload=_tool_call("read_project_file", {"path": path}),
        )
        _assert_tool_error(read_response)
        assert _tool_payload(read_response) == {"error": "repository_scope_violation"}


@pytest.mark.asyncio
async def test_generation_mcp_search_skips_invalid_utf8_but_direct_read_refuses_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "valid.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "invalid.txt").write_bytes(b"needle\xff")
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    _, search_response = await service.handle(
        token=session.token,
        payload=_tool_call("search_project_text", {"query": "needle"}),
    )
    searched = _tool_payload(search_response)
    assert searched["matchedCount"] == 1
    assert searched["truncationReasons"] == ["invalid_utf8"]

    _, read_response = await service.handle(
        token=session.token,
        payload=_tool_call("read_project_file", {"path": "invalid.txt"}),
    )
    _assert_tool_error(read_response)
    assert _tool_payload(read_response) == {"error": "invalid_utf8_refused"}


@pytest.mark.asyncio
async def test_generation_mcp_invalid_utf8_consumes_search_scan_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "invalid-a.txt").write_bytes(b"value\xff")
    (tmp_path / "invalid-b.txt").write_bytes(b"value\xff")
    (tmp_path / "valid.txt").write_text("value\n", encoding="utf-8")
    monkeypatch.setattr(
        generation_mcp_module,
        "GENERATION_DISCOVERY_SEARCH_MAX_SCAN_BYTES",
        12,
    )
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call("search_project_text", {"query": "value"}),
    )
    searched = _tool_payload(response)

    assert searched["scannedFileCount"] == 2
    assert searched["scannedByteCount"] == 12
    assert searched["matchedCount"] == 0
    assert searched["truncationReasons"] == ["invalid_utf8", "scan_byte_limit"]


@pytest.mark.asyncio
async def test_generation_mcp_search_metadata_scan_counts_toward_session_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "a.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(
        generation_mcp_module,
        "GENERATION_DISCOVERY_SESSION_MAX_SCAN_FILES",
        2,
    )
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    _, first = await service.handle(
        token=session.token,
        payload=_tool_call("search_project_text", {"query": "needle"}),
    )
    assert _tool_payload(first)["matchedCount"] == 2
    _, second = await service.handle(
        token=session.token,
        payload=_tool_call("search_project_text", {"query": "needle"}),
    )
    _assert_tool_error(second)
    assert _tool_payload(second) == {"error": "repository_scan_quota_exceeded"}


@pytest.mark.asyncio
async def test_generation_mcp_enforces_cumulative_repository_quotas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "visible.txt").write_text("visible\n", encoding="utf-8")
    monkeypatch.setattr(generation_mcp_module, "GENERATION_DISCOVERY_SESSION_MAX_CALLS", 1)
    service = StructuredPrototypeGenerationMcpService()
    session = _open_discovery_session(service, tmp_path)

    _, first = await service.handle(
        token=session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    assert _tool_payload(first)["returnedCount"] == 1
    _, second = await service.handle(
        token=session.token,
        payload=_tool_call("read_project_file", {"path": "visible.txt"}),
    )
    _assert_tool_error(second)
    assert _tool_payload(second) == {"error": "repository_call_quota_exceeded"}

    monkeypatch.setattr(generation_mcp_module, "GENERATION_DISCOVERY_SESSION_MAX_CALLS", 128)
    monkeypatch.setattr(
        generation_mcp_module,
        "GENERATION_DISCOVERY_SESSION_MAX_SCAN_FILES",
        1,
    )
    scan_service = StructuredPrototypeGenerationMcpService()
    scan_session = _open_discovery_session(scan_service, tmp_path)
    await scan_service.handle(
        token=scan_session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    _, scan_exceeded = await scan_service.handle(
        token=scan_session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    _assert_tool_error(scan_exceeded)
    assert _tool_payload(scan_exceeded) == {"error": "repository_scan_quota_exceeded"}

    monkeypatch.setattr(
        generation_mcp_module,
        "GENERATION_DISCOVERY_SESSION_MAX_SCAN_FILES",
        20_000,
    )
    monkeypatch.setattr(
        generation_mcp_module,
        "GENERATION_DISCOVERY_SESSION_MAX_RETURNED_BYTES",
        1,
    )
    returned_service = StructuredPrototypeGenerationMcpService()
    returned_session = _open_discovery_session(returned_service, tmp_path)
    _, returned_exceeded = await returned_service.handle(
        token=returned_session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    _assert_tool_error(returned_exceeded)
    assert _tool_payload(returned_exceeded) == {"error": "repository_return_quota_exceeded"}
    _, returned_retry = await returned_service.handle(
        token=returned_session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    _assert_tool_error(returned_retry)
    assert _tool_payload(returned_retry) == {"error": "repository_return_quota_exceeded"}


@pytest.mark.asyncio
async def test_generation_mcp_result_hash_excludes_session_identity(tmp_path: Path) -> None:
    (tmp_path / "visible.txt").write_text("visible\n", encoding="utf-8")
    service = StructuredPrototypeGenerationMcpService()
    first_session = _open_discovery_session(service, tmp_path)
    second_session = service.open_session(
        project_id="project-2",
        job_id="job-2",
        run_id="run-2",
        item_id="item-2",
        task_id="task-2",
        task_kind="generation_page",
        context_object_hash="sha256:" + "c" * 64,
    )
    service.bind_repository_root(
        second_session,
        task_id="task-2",
        worktree_root=tmp_path,
    )
    service.bind_execution_process(second_session, "process-2")

    _, first_response = await service.handle(
        token=first_session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )
    _, second_response = await service.handle(
        token=second_session.token,
        payload=_tool_call("list_project_files", {"pattern": "**"}),
    )

    assert (
        _tool_payload(first_response)["resultHash"] == _tool_payload(second_response)["resultHash"]
    )


@pytest.mark.asyncio
async def test_generation_blueprint_accepts_after_all_repository_discovery_tools_succeed(
    tmp_path: Path,
) -> None:
    (tmp_path / "routes.ts").write_text(
        "export const dashboardRoute = '/dashboard';\n",
        encoding="utf-8",
    )
    service = StructuredPrototypeGenerationMcpService()
    session = _open_blueprint_discovery_session(service, tmp_path)
    for name, arguments in _blueprint_discovery_calls():
        await _assert_successful_tool_call(service, session, name, arguments)

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call(
            "finalize_prototype_blueprint",
            {"payload": blueprint_payload()},
        ),
    )

    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is False
    envelope, _, process_id = service.submitted_artifact(session)
    assert envelope.task_kind == "generation_blueprint"
    assert process_id == "process-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing_tool",
    ["list_project_files", "search_project_text", "read_project_file"],
)
async def test_generation_blueprint_refuses_when_any_repository_discovery_tool_is_missing(
    tmp_path: Path,
    missing_tool: str,
) -> None:
    (tmp_path / "routes.ts").write_text(
        "export const dashboardRoute = '/dashboard';\n",
        encoding="utf-8",
    )
    service = StructuredPrototypeGenerationMcpService()
    session = _open_blueprint_discovery_session(service, tmp_path)
    for name, arguments in _blueprint_discovery_calls():
        if name != missing_tool:
            await _assert_successful_tool_call(service, session, name, arguments)

    _, response = await service.handle(
        token=session.token,
        payload=_tool_call(
            "finalize_prototype_blueprint",
            {"payload": blueprint_payload()},
        ),
    )

    _assert_tool_error(response)
    assert _tool_payload(response) == {"error": "repository_provenance_incomplete"}
    with pytest.raises(StructuredPrototypeGenerationMcpError) as error:
        service.submitted_artifact(session)
    assert error.value.code == "submission_missing"


@pytest.mark.asyncio
async def test_generation_blueprint_failed_repository_discovery_call_does_not_count(
    tmp_path: Path,
) -> None:
    (tmp_path / "routes.ts").write_text(
        "export const dashboardRoute = '/dashboard';\n",
        encoding="utf-8",
    )
    service = StructuredPrototypeGenerationMcpService()
    session = _open_blueprint_discovery_session(service, tmp_path)
    for name, arguments in _blueprint_discovery_calls():
        if name != "search_project_text":
            await _assert_successful_tool_call(service, session, name, arguments)
    _, failed_search = await service.handle(
        token=session.token,
        payload=_tool_call("search_project_text", {"query": "invalid\nquery"}),
    )
    _assert_tool_error(failed_search)
    assert _tool_payload(failed_search)["error"] == "schema_invalid"

    finalization_call = _tool_call(
        "finalize_prototype_blueprint",
        {"payload": blueprint_payload()},
    )
    _, refused = await service.handle(token=session.token, payload=finalization_call)

    _assert_tool_error(refused)
    assert _tool_payload(refused) == {"error": "repository_provenance_incomplete"}

    await _assert_successful_tool_call(
        service,
        session,
        "search_project_text",
        {"query": "dashboardRoute"},
    )
    _, accepted = await service.handle(token=session.token, payload=finalization_call)
    assert accepted is not None
    accepted_result = accepted["result"]
    assert isinstance(accepted_result, dict)
    assert accepted_result["isError"] is False
