from __future__ import annotations

import hmac
import json
import secrets
import time
from dataclasses import dataclass

from pydantic import ValidationError

from app.application import audit
from app.application.mcp_registry import (
    McpServerDescriptor,
    McpToolDescriptor,
)
from app.application.project_startup_service import (
    ProjectStartupConfigService,
    StartupConfigError,
    StartupConfigInput,
)
from app.domain.models import Project

_SERVICE_PROPERTIES: dict[str, object] = {
    "service_id": {"type": "string"},
    "name": {"type": "string"},
    "working_directory": {"type": "string"},
    "setup_command": {"type": "string"},
    "run_command": {"type": "string"},
    "access_url": {"type": ["string", "null"]},
    "depends_on": {"type": "array", "items": {"type": "string"}},
    "evidence": {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["path", "detail"],
            "properties": {
                "path": {"type": "string"},
                "detail": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
}

PROJECT_STARTUP_MCP_DESCRIPTOR = McpServerDescriptor(
    id="project-startup",
    display_name="Project Startup",
    description="Persists validated multi-service startup configuration discovered from a project.",
    owner="operations",
    scope="task",
    transport="http",
    version="1.0",
    tools=(
        McpToolDescriptor(
            id="save_startup_config",
            description=(
                "Validate and persist the complete multi-service startup configuration. "
                "Call exactly once after reading the repository evidence."
            ),
            risk_level="write",
            input_schema={
                "type": "object",
                "required": ["services", "env_vars", "notes"],
                "properties": {
                    "services": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": [
                                "service_id",
                                "name",
                                "working_directory",
                                "setup_command",
                                "run_command",
                                "access_url",
                                "depends_on",
                                "evidence",
                            ],
                            "properties": _SERVICE_PROPERTIES,
                            "additionalProperties": False,
                        },
                    },
                    "env_vars": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "value", "secret", "source"],
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": ["string", "null"]},
                                "secret": {"type": "boolean"},
                                "source": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        ),
    ),
)


@dataclass(frozen=True)
class ProjectStartupMcpSession:
    token: str
    project_id: str
    task_id: str

    def claude_config(self, endpoint: str) -> str:
        return json.dumps(
            {
                "mcpServers": {
                    "project-startup": {
                        "type": "http",
                        "url": endpoint,
                        "headers": {"X-Project-Startup-Token": self.token},
                    }
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass
class _SessionState:
    session: ProjectStartupMcpSession
    project: Project
    finalized: bool = False
    result: dict[str, object] | None = None


class ProjectStartupMcpService:
    descriptor = PROJECT_STARTUP_MCP_DESCRIPTOR

    def __init__(self, config_service: ProjectStartupConfigService) -> None:
        self.config_service = config_service
        self._sessions: dict[str, _SessionState] = {}

    def open_session(self, *, project: Project, task_id: str) -> ProjectStartupMcpSession:
        session = ProjectStartupMcpSession(
            token=secrets.token_urlsafe(32),
            project_id=project.id,
            task_id=task_id,
        )
        self._sessions[session.token] = _SessionState(session=session, project=project)
        return session

    def close_task_session(self, task_id: str) -> None:
        for token, state in list(self._sessions.items()):
            if state.session.task_id == task_id:
                self._sessions.pop(token, None)

    def finalized_result(self, task_id: str) -> dict[str, object] | None:
        for state in self._sessions.values():
            if state.session.task_id == task_id and state.finalized:
                return state.result
        return None

    def has_task_session(self, task_id: str) -> bool:
        return any(state.session.task_id == task_id for state in self._sessions.values())

    def has_session_token(self, token: str | None) -> bool:
        return token is not None and any(
            hmac.compare_digest(token, candidate) for candidate in self._sessions
        )

    def active_session_count(self) -> int:
        return len(self._sessions)

    async def handle(
        self, *, token: str | None, payload: object
    ) -> tuple[int, dict[str, object] | None]:
        if not isinstance(payload, dict):
            return 400, self._error(None, -32600, "JSON-RPC payload must be an object")
        request_id = payload.get("id")
        if payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
            return 400, self._error(request_id, -32600, "invalid JSON-RPC request")
        method = payload["method"]
        if method == "notifications/initialized":
            return 202, None
        state = self._sessions.get(token or "")
        if state is None:
            return 401, self._error(
                request_id, -32001, "project startup MCP session is unavailable"
            )
        if method == "initialize":
            return 200, self._result(
                request_id,
                {
                    "protocolVersion": self.descriptor.protocol_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.descriptor.id,
                        "version": self.descriptor.version,
                    },
                },
            )
        if method == "tools/list":
            return 200, self._result(request_id, {"tools": self.descriptor.protocol_tools()})
        if method != "tools/call":
            return 200, self._error(request_id, -32601, "MCP method is not supported")
        params = payload.get("params")
        if not isinstance(params, dict):
            return 200, self._error(request_id, -32602, "tools/call requires params")
        name = params.get("name")
        arguments = params.get("arguments", {})
        started = time.monotonic()
        if name != "save_startup_config" or not isinstance(arguments, dict):
            result = self._tool_result({"error": "unknown project startup tool"}, is_error=True)
            audit.record_mcp_call(
                server_id=self.descriptor.id,
                tool_id=name if isinstance(name, str) else "<invalid>",
                scope_id=state.session.task_id,
                task_id=state.session.task_id,
                started=started,
                is_error=True,
            )
            return 200, self._result(
                request_id,
                result,
            )
        if state.finalized:
            result = self._tool_result(
                {"error": "startup configuration is already finalized"}, is_error=True
            )
            audit.record_mcp_call(
                server_id=self.descriptor.id,
                tool_id=name,
                scope_id=state.session.task_id,
                task_id=state.session.task_id,
                started=started,
                is_error=True,
            )
            return 200, self._result(
                request_id,
                result,
            )
        try:
            config = StartupConfigInput.model_validate(arguments)
            services = await self.config_service.save_analysis(
                project=state.project,
                task_id=state.session.task_id,
                payload=config,
            )
        except (ValidationError, StartupConfigError) as exc:
            result = self._tool_result({"error": str(exc)}, is_error=True)
            audit.record_mcp_call(
                server_id=self.descriptor.id,
                tool_id=name,
                scope_id=state.session.task_id,
                task_id=state.session.task_id,
                started=started,
                is_error=True,
            )
            return 200, self._result(
                request_id,
                result,
            )
        state.result = {
            "services": [service.model_dump(mode="json") for service in services],
            "env_vars": [item.model_dump(mode="json") for item in config.env_vars],
            "notes": config.notes,
        }
        state.finalized = True
        result = self._tool_result({"saved": True, "service_count": len(services)})
        audit.record_mcp_call(
            server_id=self.descriptor.id,
            tool_id=name,
            scope_id=state.session.task_id,
            task_id=state.session.task_id,
            started=started,
            is_error=False,
        )
        return 200, self._result(
            request_id,
            result,
        )

    @staticmethod
    def _tools() -> list[dict[str, object]]:
        return PROJECT_STARTUP_MCP_DESCRIPTOR.protocol_tools()

    @staticmethod
    def _tool_result(value: object, *, is_error: bool = False) -> dict[str, object]:
        return {
            "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
            "isError": is_error,
        }

    @staticmethod
    def _result(request_id: object, value: dict[str, object]) -> dict[str, object]:
        return {"jsonrpc": "2.0", "id": request_id, "result": value}

    @staticmethod
    def _error(request_id: object, code: int, message: str) -> dict[str, object]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
