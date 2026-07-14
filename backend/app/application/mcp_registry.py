from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, Protocol

from app.application.audit import CATEGORY_TOOL_RESULT
from app.domain.models import AuditLog
from app.json_safety import JsonObject, parse_json_object

MCP_PROTOCOL_VERSION = "2025-03-26"

McpRiskLevel = Literal["read", "write", "execute"]
McpScope = Literal["plan", "task", "project", "system"]
McpAvailability = Literal["available", "unavailable"]


@dataclass(frozen=True)
class McpToolDescriptor:
    id: str
    description: str
    risk_level: McpRiskLevel
    input_schema: JsonObject

    def protocol_payload(self) -> JsonObject:
        return {
            "name": self.id,
            "description": self.description,
            "inputSchema": deepcopy(self.input_schema),
        }


@dataclass(frozen=True)
class McpServerDescriptor:
    id: str
    display_name: str
    description: str
    owner: str
    scope: McpScope
    transport: Literal["http"]
    version: str
    tools: tuple[McpToolDescriptor, ...]
    protocol_version: str = MCP_PROTOCOL_VERSION

    def protocol_tools(self) -> list[JsonObject]:
        return [tool.protocol_payload() for tool in self.tools]


class McpRuntimeProvider(Protocol):
    def active_session_count(self) -> int: ...


@dataclass(frozen=True)
class McpRegistration:
    descriptor: McpServerDescriptor
    runtime: McpRuntimeProvider | None


class McpRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, McpRegistration] = {}

    def register(
        self,
        descriptor: McpServerDescriptor,
        runtime: McpRuntimeProvider | None,
    ) -> None:
        if descriptor.id in self._registrations:
            raise ValueError(f"duplicate MCP server id: {descriptor.id}")
        tool_ids = [tool.id for tool in descriptor.tools]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError(f"duplicate MCP tool id in server: {descriptor.id}")
        self._registrations[descriptor.id] = McpRegistration(
            descriptor=descriptor,
            runtime=runtime,
        )

    def registrations(self) -> tuple[McpRegistration, ...]:
        return tuple(self._registrations.values())


class McpAuditStore(Protocol):
    async def list_audit_logs(
        self,
        *,
        categories: list[str] | None = None,
        q: str | None = None,
        limit: int = 200,
        descending: bool = True,
    ) -> list[AuditLog]: ...


@dataclass(frozen=True)
class _McpCall:
    id: str
    server_id: str
    tool_id: str
    task_id: str | None
    scope_id: str | None
    status: str | None
    duration_ms: int | None
    created_at: str | None
    error: str | None

    def payload(self) -> JsonObject:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "tool_id": self.tool_id,
            "task_id": self.task_id,
            "scope_id": self.scope_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "error": self.error,
        }


def _parse_mcp_call(row: AuditLog) -> _McpCall | None:
    payload = parse_json_object(row.payload_json)
    if payload is None or payload.get("transport") != "mcp":
        return None
    server_id = payload.get("server_id")
    tool_id = payload.get("tool_id")
    scope_id = payload.get("scope_id")
    if not isinstance(server_id, str) or not isinstance(tool_id, str):
        return None
    return _McpCall(
        id=row.id,
        server_id=server_id,
        tool_id=tool_id,
        task_id=row.task_id,
        scope_id=scope_id if isinstance(scope_id, str) else None,
        status=row.status,
        duration_ms=row.duration_ms,
        created_at=row.created_at.isoformat() if row.created_at is not None else None,
        error=row.error,
    )


def _call_metrics(calls: list[_McpCall]) -> JsonObject:
    return {
        "recent_call_count": len(calls),
        "error_call_count": sum(call.status == "error" for call in calls),
        "last_called_at": calls[0].created_at if calls else None,
    }


class McpManagementService:
    AUDIT_WINDOW = 500
    RECENT_CALL_LIMIT = 50

    def __init__(self, registry: McpRegistry, audit_store: McpAuditStore) -> None:
        self._registry = registry
        self._audit_store = audit_store

    async def catalog(self) -> JsonObject:
        rows = await self._audit_store.list_audit_logs(
            categories=[CATEGORY_TOOL_RESULT],
            q="mcp:",
            limit=self.AUDIT_WINDOW,
            descending=True,
        )
        calls = [call for row in rows if (call := _parse_mcp_call(row)) is not None]
        servers: list[JsonObject] = []
        registered_ids: set[str] = set()
        for registration in self._registry.registrations():
            descriptor = registration.descriptor
            registered_ids.add(descriptor.id)
            server_calls = [call for call in calls if call.server_id == descriptor.id]
            runtime = registration.runtime
            availability: McpAvailability = "available" if runtime is not None else "unavailable"
            tools: list[JsonObject] = []
            for tool in descriptor.tools:
                tool_calls = [call for call in server_calls if call.tool_id == tool.id]
                tools.append(
                    {
                        "id": tool.id,
                        "description": tool.description,
                        "risk_level": tool.risk_level,
                        "input_schema": deepcopy(tool.input_schema),
                        **_call_metrics(tool_calls),
                    }
                )
            servers.append(
                {
                    "id": descriptor.id,
                    "display_name": descriptor.display_name,
                    "description": descriptor.description,
                    "owner": descriptor.owner,
                    "scope": descriptor.scope,
                    "protocol_version": descriptor.protocol_version,
                    "transport": descriptor.transport,
                    "version": descriptor.version,
                    "availability": availability,
                    "active_session_count": runtime.active_session_count()
                    if runtime is not None
                    else 0,
                    "tool_count": len(descriptor.tools),
                    "tools": tools,
                    **_call_metrics(server_calls),
                }
            )
        recent_calls = [call.payload() for call in calls if call.server_id in registered_ids]
        return {
            "servers": servers,
            "recent_calls": recent_calls[: self.RECENT_CALL_LIMIT],
            "audit_window_size": self.AUDIT_WINDOW,
        }
