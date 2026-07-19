from __future__ import annotations

import hashlib
import json

import pytest

from app.adapters.prototype_object_store import canonical_json_bytes
from app.application.structured_prototype_ai_mcp import PrototypeAiMcpService


def _tool_call(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "submit_prototype_assistant_outcome",
            "arguments": arguments,
        },
    }


def _arguments(outcome: object) -> dict[str, object]:
    return {
        "outcomeJson": json.dumps(
            outcome,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    }


def _result(response: dict[str, object] | None) -> dict[str, object]:
    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    return result


@pytest.mark.asyncio
async def test_scoped_mcp_accepts_one_idempotent_strict_outcome() -> None:
    service = PrototypeAiMcpService()
    session = service.open_session(
        project_id="project-1",
        edit_run_id="run-1",
        task_id="task-1",
    )
    service.bind_execution_process(session, "process-1")
    outcome_payload = {
        "contractVersion": 1,
        "kind": "answer",
        "message": "当前原型有三页。",
    }
    arguments = _arguments(outcome_payload)

    status, first = await service.handle(token=session.token, payload=_tool_call(arguments))
    retry_status, retry = await service.handle(token=session.token, payload=_tool_call(arguments))
    conflict_status, conflict = await service.handle(
        token=session.token,
        payload=_tool_call(
            _arguments(
                {
                    "contractVersion": 1,
                    "kind": "answer",
                    "message": "不同结果",
                }
            )
        ),
    )

    assert status == retry_status == conflict_status == 200
    assert first == retry
    assert _result(conflict)["isError"] is True
    outcome, receipt, process_id = service.submitted_outcome(session)
    assert outcome.kind == "answer"
    assert process_id == "process-1"
    assert (
        receipt.request_hash
        == "sha256:" + hashlib.sha256(canonical_json_bytes(arguments)).hexdigest()
    )
    service.close_session(session)
    assert service.active_session_count() == 0


@pytest.mark.asyncio
async def test_scoped_mcp_refuses_submission_before_process_binding() -> None:
    service = PrototypeAiMcpService()
    session = service.open_session(
        project_id="project-1",
        edit_run_id="run-1",
        task_id="task-1",
    )
    status, response = await service.handle(
        token=session.token,
        payload=_tool_call(
            _arguments(
                {
                    "contractVersion": 1,
                    "kind": "answer",
                    "message": "不应接受",
                }
            )
        ),
    )
    assert status == 200
    assert _result(response)["isError"] is True


@pytest.mark.asyncio
async def test_scoped_mcp_refuses_invalid_outcome_json() -> None:
    service = PrototypeAiMcpService()
    session = service.open_session(
        project_id="project-1",
        edit_run_id="run-1",
        task_id="task-1",
    )
    service.bind_execution_process(session, "process-1")

    status, response = await service.handle(
        token=session.token,
        payload=_tool_call({"outcomeJson": "{invalid"}),
    )

    assert status == 200
    result = _result(response)
    assert result["isError"] is True
    content = result["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    text = first["text"]
    assert isinstance(text, str)
    payload = json.loads(text)
    assert payload == {
        "error": "schema_invalid",
        "issues": [{"path": "outcomeJson", "type": "json_invalid"}],
    }


def test_scoped_mcp_exposes_bounded_json_string_contract() -> None:
    tools = PrototypeAiMcpService.descriptor.protocol_tools()
    submission = next(
        tool for tool in tools if tool["name"] == "submit_prototype_assistant_outcome"
    )
    schema = submission["inputSchema"]
    assert isinstance(schema, dict)

    assert schema["required"] == ["outcomeJson"]
    properties = schema["properties"]
    assert isinstance(properties, dict)
    outcome_schema = properties["outcomeJson"]
    assert isinstance(outcome_schema, dict)
    assert outcome_schema["type"] == "string"
    assert "$defs" in schema
    assert "x-outcomeSchema" in schema
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    assert {
        "AddPageCommandV1",
        "DeletePageCommandV1",
        "DuplicatePageCommandV1",
        "RenamePageCommandV1",
        "UpdateNodeNameCommandV1",
    } <= set(definitions)
