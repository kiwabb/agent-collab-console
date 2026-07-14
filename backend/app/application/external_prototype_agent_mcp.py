from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.external_prototype_agent_service import (
    MCP_SERVER_ID,
    ExternalPrototypeAgentError,
    ExternalPrototypeAgentService,
)
from app.domain.external_prototype_agent import ExternalAgentPairingRecord
from app.json_safety import JsonObject

SUPPORTED_MCP_PROTOCOL_VERSIONS = frozenset(
    {
        "2024-11-05",
        "2025-03-26",
        "2025-06-18",
    }
)
LATEST_MCP_PROTOCOL_VERSION = "2025-06-18"


class StrictMcpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    meta: JsonObject | None = Field(default=None, alias="_meta")


class McpClientInfo(StrictMcpModel):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=128)
    websiteUrl: str | None = Field(default=None, min_length=1, max_length=2_048)
    icons: list[JsonObject] = Field(default_factory=list, max_length=8)


class McpInitializeParams(StrictMcpModel):
    protocolVersion: str = Field(min_length=1, max_length=32)
    capabilities: JsonObject
    clientInfo: McpClientInfo


class McpListToolsParams(StrictMcpModel):
    cursor: str | None = Field(default=None, min_length=1, max_length=512)


class McpCallToolParams(StrictMcpModel):
    name: str = Field(min_length=1, max_length=128)
    arguments: JsonObject = Field(default_factory=dict)


class McpEmptyParams(StrictMcpModel):
    pass


@dataclass(frozen=True, slots=True)
class ExternalAgentMcpDispatchResult:
    body: JsonObject | None
    status_code: int = 200


class ExternalAgentMcpProtocolError(ValueError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class ExternalPrototypeAgentMcpHandler:
    def __init__(self, service: ExternalPrototypeAgentService) -> None:
        self._service = service

    async def handle(
        self,
        pairing: ExternalAgentPairingRecord,
        payload: object,
    ) -> ExternalAgentMcpDispatchResult:
        request_id: str | int | None = None
        try:
            request = self._request_object(payload)
            request_id = self._request_id(request)
            method = self._method(request)
            params = request.get("params", {})

            if method == "notifications/initialized":
                self._require_notification(request)
                self._parse(McpEmptyParams, params)
                await self._service.record_protocol_event(pairing, "mcp_initialized")
                return ExternalAgentMcpDispatchResult(body=None, status_code=202)
            self._require_request_id(request)
            if method == "initialize":
                initialize = self._parse(McpInitializeParams, params)
                protocol_version = (
                    initialize.protocolVersion
                    if initialize.protocolVersion in SUPPORTED_MCP_PROTOCOL_VERSIONS
                    else LATEST_MCP_PROTOCOL_VERSION
                )
                await self._service.record_protocol_event(pairing, "mcp_initialize")
                return self._success(
                    request_id,
                    {
                        "protocolVersion": protocol_version,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {
                            "name": MCP_SERVER_ID,
                            "version": "1.0.0",
                        },
                        "instructions": (
                            "Read bounded prototype context and submit command proposals. "
                            "Apply and Publish remain human-controlled."
                        ),
                    },
                )
            if method == "ping":
                self._parse(McpEmptyParams, params)
                return self._success(request_id, {})
            if method == "tools/list":
                self._parse(McpListToolsParams, params)
                await self._service.record_protocol_event(pairing, "mcp_tools_listed")
                return self._success(
                    request_id,
                    {"tools": self._service.tool_descriptors(pairing)},
                )
            if method == "tools/call":
                call = self._parse(McpCallToolParams, params)
                try:
                    result = await self._service.invoke_tool(
                        pairing,
                        call.name,
                        call.arguments,
                    )
                except ExternalPrototypeAgentError as exc:
                    return self._tool_error(request_id, exc)
                return self._success(
                    request_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    result,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                    allow_nan=False,
                                ),
                            }
                        ],
                        "structuredContent": result,
                        "isError": False,
                    },
                )
            raise ExternalAgentMcpProtocolError(-32601, "method_not_found")
        except ExternalAgentMcpProtocolError as exc:
            return self._failure(request_id, exc.code, str(exc))
        except ValidationError:
            return self._failure(request_id, -32602, "invalid_params")

    @staticmethod
    def _request_object(payload: object) -> JsonObject:
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            raise ExternalAgentMcpProtocolError(-32600, "invalid_request")
        return payload

    @staticmethod
    def _request_id(request: JsonObject) -> str | int | None:
        request_id = request.get("id")
        if request_id is None:
            return None
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            raise ExternalAgentMcpProtocolError(-32600, "invalid_request")
        return request_id

    @staticmethod
    def _method(request: JsonObject) -> str:
        method = request.get("method")
        if not isinstance(method, str) or not method:
            raise ExternalAgentMcpProtocolError(-32600, "invalid_request")
        return method

    @staticmethod
    def _require_notification(request: JsonObject) -> None:
        if "id" in request:
            raise ExternalAgentMcpProtocolError(-32600, "invalid_request")

    @staticmethod
    def _require_request_id(request: JsonObject) -> None:
        if "id" not in request or request["id"] is None:
            raise ExternalAgentMcpProtocolError(-32600, "invalid_request")

    @staticmethod
    def _parse[ModelT: StrictMcpModel](model_type: type[ModelT], value: object) -> ModelT:
        return model_type.model_validate(value, strict=True)

    @staticmethod
    def _success(
        request_id: str | int | None,
        result: JsonObject,
    ) -> ExternalAgentMcpDispatchResult:
        return ExternalAgentMcpDispatchResult(
            body={"jsonrpc": "2.0", "id": request_id, "result": result}
        )

    @staticmethod
    def _failure(
        request_id: str | int | None,
        code: int,
        message: str,
    ) -> ExternalAgentMcpDispatchResult:
        return ExternalAgentMcpDispatchResult(
            body={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    @staticmethod
    def _tool_error(
        request_id: str | int | None,
        error: ExternalPrototypeAgentError,
    ) -> ExternalAgentMcpDispatchResult:
        error_payload: JsonObject = {
            "code": error.code,
            "retryable": error.retryable,
        }
        return ExternalPrototypeAgentMcpHandler._success(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(error_payload, sort_keys=True, separators=(",", ":")),
                    }
                ],
                "structuredContent": {"error": error_payload},
                "isError": True,
            },
        )
