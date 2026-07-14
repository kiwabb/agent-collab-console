from __future__ import annotations

from datetime import datetime

import pytest

from app.application import audit
from app.application.audit.writer import audit_logger
from app.application.mcp_registry import (
    McpManagementService,
    McpRegistry,
    McpServerDescriptor,
    McpToolDescriptor,
)
from app.domain.models import AuditLog


class Runtime:
    def active_session_count(self) -> int:
        return 2


class Store:
    def __init__(self, rows: list[AuditLog]) -> None:
        self.rows = rows

    async def list_audit_logs(
        self,
        *,
        categories: list[str] | None = None,
        q: str | None = None,
        limit: int = 200,
        descending: bool = True,
    ) -> list[AuditLog]:
        assert categories == ["tool_result"]
        assert q == "mcp:"
        assert limit == 500
        assert descending is True
        return self.rows


def _descriptor(server_id: str = "example") -> McpServerDescriptor:
    return McpServerDescriptor(
        id=server_id,
        display_name="Example",
        description="Example MCP",
        owner="tests",
        scope="task",
        transport="http",
        version="1.0",
        tools=(
            McpToolDescriptor(
                id="save",
                description="Save a value",
                risk_level="write",
                input_schema={"type": "object"},
            ),
        ),
    )


def _json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            key.lower()
            for key, child in value.items()
            if isinstance(key, str)
        } | set().union(*(_json_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_json_keys(child) for child in value))
    return set()


def test_registry_rejects_duplicate_server_ids() -> None:
    registry = McpRegistry()
    registry.register(_descriptor(), Runtime())

    with pytest.raises(ValueError, match="duplicate MCP server id"):
        registry.register(_descriptor(), Runtime())


@pytest.mark.asyncio
async def test_catalog_combines_registry_runtime_and_redacted_audit_rows() -> None:
    registry = McpRegistry()
    registry.register(_descriptor(), Runtime())
    row = AuditLog(
        id="audit-1",
        category="tool_result",
        actor="mcp:example",
        task_id="task-1",
        status="ok",
        duration_ms=12,
        created_at=datetime(2026, 7, 13, 10, 30),
        payload_json=(
            '{"transport":"mcp","server_id":"example","tool_id":"save","scope_id":"task-1"}'
        ),
    )

    catalog = await McpManagementService(registry, Store([row])).catalog()

    servers = catalog["servers"]
    assert isinstance(servers, list)
    server = servers[0]
    assert server["availability"] == "available"
    assert server["active_session_count"] == 2
    assert server["recent_call_count"] == 1
    assert server["tools"][0]["risk_level"] == "write"
    calls = catalog["recent_calls"]
    assert isinstance(calls, list)
    call = calls[0]
    assert isinstance(call, dict)
    assert call == {
        "id": "audit-1",
        "server_id": "example",
        "tool_id": "save",
        "task_id": "task-1",
        "scope_id": "task-1",
        "status": "ok",
        "duration_ms": 12,
        "created_at": "2026-07-13T10:30:00",
        "error": None,
    }
    assert "arguments" not in call
    assert "token" not in call


def test_registered_descriptors_drive_protocol_tool_payloads() -> None:
    descriptor = _descriptor()

    tools = descriptor.protocol_tools()

    assert tools == [
        {
            "name": "save",
            "description": "Save a value",
            "inputSchema": {"type": "object"},
        }
    ]
    tools[0]["inputSchema"] = {"mutated": True}
    assert descriptor.tools[0].input_schema == {"type": "object"}


def test_mcp_catalog_endpoint_lists_framework_owned_servers(client) -> None:
    response = client.get("/api/mcp/catalog")

    assert response.status_code == 200
    payload = response.json()
    servers = {server["id"]: server for server in payload["servers"]}
    assert set(servers) == {
        "project-startup",
        "prototype-planning",
        "structured-prototype-ai",
        "structured-prototype-generation",
    }
    assert {tool["id"] for tool in servers["project-startup"]["tools"]} == {"save_startup_config"}
    assert {tool["id"] for tool in servers["prototype-planning"]["tools"]} == {
        "list_discovered_pages",
        "register_prototype_page",
        "finalize_prototype_inventory",
    }
    assert {tool["id"] for tool in servers["structured-prototype-ai"]["tools"]} == {
        "submit_prototype_assistant_outcome"
    }
    assert {
        tool["id"] for tool in servers["structured-prototype-generation"]["tools"]
    } == {
        "get_generation_submission_context",
        "finalize_prototype_blueprint",
        "finalize_prototype_foundation",
        "finalize_prototype_page",
    }
    assert servers["structured-prototype-ai"]["availability"] == "available"
    assert servers["structured-prototype-generation"]["availability"] == "available"
    assert _json_keys(payload).isdisjoint(
        {"token", "session_token", "access_token", "authorization"}
    )


def test_mcp_audit_record_never_contains_arguments_or_results(monkeypatch) -> None:
    recorded: list[tuple[str, dict[str, object]]] = []

    def capture(category: str, **fields: object) -> None:
        recorded.append((category, fields))

    monkeypatch.setattr(audit_logger, "record", capture)

    audit.record_mcp_call(
        server_id="project-startup",
        tool_id="save_startup_config",
        scope_id="task-1",
        task_id="task-1",
        started=0.0,
        is_error=False,
    )

    assert len(recorded) == 1
    category, fields = recorded[0]
    assert category == "tool_result"
    assert fields["payload"] == {
        "transport": "mcp",
        "server_id": "project-startup",
        "tool_id": "save_startup_config",
        "scope_id": "task-1",
    }
    serialized = str(fields).lower()
    assert "arguments" not in serialized
    assert "result" not in serialized
    assert "token" not in serialized
