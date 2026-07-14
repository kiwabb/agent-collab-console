from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from app.adapters.prototype_object_store import canonical_json_bytes
from app.application import audit
from app.application.mcp_registry import McpServerDescriptor, McpToolDescriptor
from app.application.structured_prototype_ai_contracts import (
    PrototypeAssistantOutcomeEnvelopeV1,
    PrototypeAssistantOutcomeV1,
    assistant_outcome_payload,
    parse_prototype_assistant_outcome,
)
from app.application.structured_prototype_contracts import StructuredPrototypeContractError

PROTOTYPE_AI_MCP_MAX_BYTES = 256 * 1024


def _outcome_json_input_schema() -> dict[str, object]:
    envelope_schema = PrototypeAssistantOutcomeEnvelopeV1.model_json_schema(by_alias=True)
    definitions = envelope_schema.pop("$defs", None)
    properties = envelope_schema["properties"]
    outcome_schema = properties["outcome"]
    input_schema: dict[str, object] = {
        "type": "object",
        "required": ["outcomeJson"],
        "properties": {
            "outcomeJson": {
                "type": "string",
                "minLength": 2,
                "maxLength": PROTOTYPE_AI_MCP_MAX_BYTES,
                "description": (
                    "Complete strict JSON serialization of one assistant outcome matching "
                    "x-outcomeSchema. Encode command and affected-entity arrays inside this "
                    "JSON string."
                ),
            }
        },
        "additionalProperties": False,
        "x-outcomeSchema": outcome_schema,
    }
    if definitions is not None:
        input_schema["$defs"] = definitions
    return input_schema

PROTOTYPE_AI_MCP_DESCRIPTOR = McpServerDescriptor(
    id="structured-prototype-ai",
    display_name="Structured Prototype AI",
    description="Accepts one task-scoped structured prototype assistant outcome.",
    owner="prototype",
    scope="task",
    transport="http",
    version="1.0",
    tools=(
        McpToolDescriptor(
            id="submit_prototype_assistant_outcome",
            description="Submit one strict answer, clarification, or domain-command proposal.",
            risk_level="write",
            input_schema=_outcome_json_input_schema(),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class PrototypeAiMcpSession:
    token: str
    project_id: str
    edit_run_id: str
    task_id: str

    def claude_config(self, endpoint: str) -> str:
        return json.dumps(
            {
                "mcpServers": {
                    "structured-prototype-ai": {
                        "type": "http",
                        "url": endpoint,
                        "headers": {"X-Prototype-Ai-Token": self.token},
                    }
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class PrototypeAiSubmissionReceipt:
    submission_id: str
    request_hash: str
    accepted_at: float


@dataclass(slots=True)
class _SessionState:
    session: PrototypeAiMcpSession
    execution_process_id: str | None = None
    request_hash: str | None = None
    receipt: PrototypeAiSubmissionReceipt | None = None
    outcome: PrototypeAssistantOutcomeV1 | None = None


class PrototypeAiMcpService:
    descriptor = PROTOTYPE_AI_MCP_DESCRIPTOR

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}

    def open_session(
        self,
        *,
        project_id: str,
        edit_run_id: str,
        task_id: str,
    ) -> PrototypeAiMcpSession:
        session = PrototypeAiMcpSession(
            token=secrets.token_urlsafe(32),
            project_id=project_id,
            edit_run_id=edit_run_id,
            task_id=task_id,
        )
        self._sessions[session.token] = _SessionState(session=session)
        return session

    def bind_execution_process(
        self,
        session: PrototypeAiMcpSession,
        execution_process_id: str,
    ) -> None:
        state = self._sessions.get(session.token)
        if state is None:
            raise RuntimeError("prototype AI MCP session is unavailable")
        if state.execution_process_id is not None and state.execution_process_id != execution_process_id:
            raise RuntimeError("prototype AI MCP process identity changed")
        state.execution_process_id = execution_process_id

    def close_session(self, session: PrototypeAiMcpSession) -> None:
        self._sessions.pop(session.token, None)

    def has_session_token(self, token: str | None) -> bool:
        return token is not None and any(
            hmac.compare_digest(token, candidate) for candidate in self._sessions
        )

    def active_session_count(self) -> int:
        return len(self._sessions)

    def submitted_outcome(
        self,
        session: PrototypeAiMcpSession,
    ) -> tuple[PrototypeAssistantOutcomeV1, PrototypeAiSubmissionReceipt, str]:
        state = self._sessions.get(session.token)
        if (
            state is None
            or state.outcome is None
            or state.receipt is None
            or state.execution_process_id is None
        ):
            raise PrototypeAiMcpError(
                "submission_missing",
                "prototype AI task did not submit an assistant outcome",
            )
        return state.outcome, state.receipt, state.execution_process_id

    async def handle(
        self,
        *,
        token: str | None,
        payload: object,
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
                request_id,
                -32001,
                "prototype AI MCP session is unavailable",
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
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return 200, self._error(request_id, -32602, "invalid tool call")
        started = time.monotonic()
        result = self._call_tool(state, name, arguments)
        audit.record_mcp_call(
            server_id=self.descriptor.id,
            tool_id=name,
            scope_id=state.session.edit_run_id,
            task_id=state.session.task_id,
            started=started,
            is_error=result["isError"] is True,
        )
        return 200, self._result(request_id, result)

    def _call_tool(
        self,
        state: _SessionState,
        name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        if name != "submit_prototype_assistant_outcome":
            return self._tool_result({"error": "submission_scope_violation"}, is_error=True)
        if state.execution_process_id is None:
            return self._tool_result({"error": "submission_scope_violation"}, is_error=True)
        if set(arguments) != {"outcomeJson"}:
            return self._tool_result({"error": "schema_invalid"}, is_error=True)
        raw = canonical_json_bytes(arguments)
        if len(raw) > PROTOTYPE_AI_MCP_MAX_BYTES:
            return self._tool_result({"error": "limit_exceeded"}, is_error=True)
        request_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        if state.request_hash is not None:
            if state.request_hash != request_hash or state.receipt is None:
                return self._tool_result({"error": "submission_conflict"}, is_error=True)
            return self._tool_result(self._receipt_payload(state.receipt))
        raw_outcome_json = arguments["outcomeJson"]
        if not isinstance(raw_outcome_json, str):
            return self._tool_result(
                {
                    "error": "schema_invalid",
                    "issues": [{"path": "outcomeJson", "type": "string_type"}],
                },
                is_error=True,
            )
        try:
            raw_outcome = json.loads(
                raw_outcome_json,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, ValueError):
            return self._tool_result(
                {
                    "error": "schema_invalid",
                    "issues": [{"path": "outcomeJson", "type": "json_invalid"}],
                },
                is_error=True,
            )
        try:
            outcome = parse_prototype_assistant_outcome(raw_outcome)
        except StructuredPrototypeContractError:
            return self._tool_result(
                {
                    "error": "schema_invalid",
                    "issues": [{"path": "outcomeJson", "type": "schema_invalid"}],
                },
                is_error=True,
            )
        accepted_at = time.time()
        receipt = PrototypeAiSubmissionReceipt(
            submission_id="prototype-ai-submission-" + secrets.token_hex(16),
            request_hash=request_hash,
            accepted_at=accepted_at,
        )
        state.request_hash = request_hash
        state.receipt = receipt
        state.outcome = outcome
        return self._tool_result(self._receipt_payload(receipt))

    @staticmethod
    def _receipt_payload(receipt: PrototypeAiSubmissionReceipt) -> dict[str, object]:
        return {
            "submissionId": receipt.submission_id,
            "requestHash": receipt.request_hash,
            "acceptedAt": receipt.accepted_at,
            "status": "staged",
        }

    @staticmethod
    def outcome_hash(outcome: PrototypeAssistantOutcomeV1) -> str:
        raw = canonical_json_bytes(assistant_outcome_payload(outcome))
        return "sha256:" + hashlib.sha256(raw).hexdigest()

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


class PrototypeAiMcpError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant is not accepted: {value}")
