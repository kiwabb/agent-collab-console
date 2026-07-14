from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.adapters.prototype_object_store import canonical_json_bytes
from app.application import audit
from app.application.mcp_registry import McpServerDescriptor, McpToolDescriptor
from app.application.structured_prototype_generation_contracts import (
    GeneratedPageV1,
    GenerationArtifactEnvelopeV1,
    GenerationBlueprintEnvelopeV1,
    GenerationBlueprintV1,
    GenerationFoundationEnvelopeV1,
    GenerationFoundationV1,
    GenerationPageEnvelopeV1,
    GenerationTaskKind,
)

GENERATION_MCP_PAYLOAD_MAX_BYTES = 64 * 1024
_DECIMAL_INTEGER_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")

_TOOL_FOR_KIND: dict[GenerationTaskKind, str] = {
    "generation_blueprint": "finalize_prototype_blueprint",
    "generation_foundation": "finalize_prototype_foundation",
    "generation_page": "finalize_prototype_page",
}


_PAYLOAD_MODEL_BY_KIND: dict[GenerationTaskKind, type[BaseModel]] = {
    "generation_blueprint": GenerationBlueprintV1,
    "generation_foundation": GenerationFoundationV1,
    "generation_page": GeneratedPageV1,
}


def _payload_input_schema(task_kind: GenerationTaskKind) -> dict[str, object]:
    payload_schema = _PAYLOAD_MODEL_BY_KIND[task_kind].model_json_schema(by_alias=True)
    definitions = payload_schema.pop("$defs", None)
    if task_kind == "generation_page":
        page_input_schema: dict[str, object] = {
            "type": "object",
            "required": ["payloadJson"],
            "properties": {
                "payloadJson": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": GENERATION_MCP_PAYLOAD_MAX_BYTES,
                    "description": (
                        "Complete strict JSON serialization of one generated page matching "
                        "x-payloadSchema. Arrays must be encoded inside this JSON string."
                    ),
                }
            },
            "additionalProperties": False,
            "x-payloadSchema": payload_schema,
        }
        if definitions is not None:
            page_input_schema["$defs"] = definitions
        return page_input_schema
    input_schema: dict[str, object] = {
        "type": "object",
        "required": ["payload"],
        "properties": {"payload": payload_schema},
        "additionalProperties": False,
    }
    if definitions is not None:
        input_schema["$defs"] = definitions
    return input_schema


GENERATION_MCP_DESCRIPTOR = McpServerDescriptor(
    id="structured-prototype-generation",
    display_name="Structured Prototype Generation",
    description="Finalizes one task-scoped structured prototype generation artifact.",
    owner="prototype",
    scope="task",
    transport="http",
    version="1.0",
    tools=(
        McpToolDescriptor(
            id="get_generation_submission_context",
            description="Read the current task and execution identities required by finalization.",
            risk_level="read",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        *tuple(
            McpToolDescriptor(
                id=tool_id,
                description=description,
                risk_level="write",
                input_schema=_payload_input_schema(
                    next(kind for kind, candidate in _TOOL_FOR_KIND.items() if candidate == tool_id)
                ),
            )
            for tool_id, description in (
                ("finalize_prototype_blueprint", "Finalize a blueprint JSON artifact."),
                ("finalize_prototype_foundation", "Finalize a foundation JSON artifact."),
                ("finalize_prototype_page", "Finalize one generated page JSON artifact."),
            )
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class GenerationMcpSession:
    token: str
    project_id: str
    job_id: str
    run_id: str
    item_id: str
    task_id: str
    task_kind: GenerationTaskKind
    context_object_hash: str

    @property
    def allowed_tool(self) -> str:
        return _TOOL_FOR_KIND[self.task_kind]

    def claude_config(self, endpoint: str) -> str:
        return json.dumps(
            {
                "mcpServers": {
                    "structured-prototype-generation": {
                        "type": "http",
                        "url": endpoint,
                        "headers": {"X-Prototype-Generation-Token": self.token},
                    }
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class GenerationSubmissionReceipt:
    submission_id: str
    request_hash: str
    accepted_at: float
    normalized_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class _SessionState:
    session: GenerationMcpSession
    execution_process_id: str | None = None
    request_hash: str | None = None
    receipt: GenerationSubmissionReceipt | None = None
    envelope: GenerationArtifactEnvelopeV1 | None = None


class StructuredPrototypeGenerationMcpService:
    descriptor = GENERATION_MCP_DESCRIPTOR

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}

    def open_session(
        self,
        *,
        project_id: str,
        job_id: str,
        run_id: str,
        item_id: str,
        task_id: str,
        task_kind: GenerationTaskKind,
        context_object_hash: str,
    ) -> GenerationMcpSession:
        session = GenerationMcpSession(
            token=secrets.token_urlsafe(32),
            project_id=project_id,
            job_id=job_id,
            run_id=run_id,
            item_id=item_id,
            task_id=task_id,
            task_kind=task_kind,
            context_object_hash=context_object_hash,
        )
        self._sessions[session.token] = _SessionState(session=session)
        return session

    def bind_execution_process(
        self,
        session: GenerationMcpSession,
        execution_process_id: str,
    ) -> None:
        state = self._sessions.get(session.token)
        if state is None:
            raise RuntimeError("structured prototype generation MCP session is unavailable")
        if (
            state.execution_process_id is not None
            and state.execution_process_id != execution_process_id
        ):
            raise RuntimeError("structured prototype generation MCP process identity changed")
        state.execution_process_id = execution_process_id

    def close_session(self, session: GenerationMcpSession) -> None:
        self._sessions.pop(session.token, None)

    def has_session_token(self, token: str | None) -> bool:
        return token is not None and any(
            hmac.compare_digest(token, candidate) for candidate in self._sessions
        )

    def active_session_count(self) -> int:
        return len(self._sessions)

    def submitted_artifact(
        self,
        session: GenerationMcpSession,
    ) -> tuple[GenerationArtifactEnvelopeV1, GenerationSubmissionReceipt, str]:
        state = self._sessions.get(session.token)
        if (
            state is None
            or state.envelope is None
            or state.receipt is None
            or state.execution_process_id is None
        ):
            raise StructuredPrototypeGenerationMcpError(
                "submission_missing",
                "structured prototype generation task did not finalize its artifact",
            )
        return state.envelope, state.receipt, state.execution_process_id

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
                "structured prototype generation MCP session is unavailable",
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
            scope_id=state.session.item_id,
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
        session = state.session
        if name == "get_generation_submission_context":
            if arguments or state.execution_process_id is None:
                return self._tool_result({"error": "submission_scope_violation"}, is_error=True)
            return self._tool_result(
                {
                    "projectId": session.project_id,
                    "jobId": session.job_id,
                    "runId": session.run_id,
                    "itemId": session.item_id,
                    "taskId": session.task_id,
                    "executionProcessId": state.execution_process_id,
                    "taskKind": session.task_kind,
                    "contextObjectHash": session.context_object_hash,
                    "allowedFinalizationTool": session.allowed_tool,
                }
            )
        if name != session.allowed_tool or state.execution_process_id is None:
            return self._tool_result({"error": "submission_scope_violation"}, is_error=True)
        argument_name = "payloadJson" if session.task_kind == "generation_page" else "payload"
        if set(arguments) != {argument_name}:
            return self._tool_result({"error": "schema_invalid"}, is_error=True)
        raw = canonical_json_bytes(arguments)
        if len(raw) > GENERATION_MCP_PAYLOAD_MAX_BYTES:
            return self._tool_result({"error": "limit_exceeded"}, is_error=True)
        request_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        if state.request_hash is not None:
            if state.request_hash != request_hash or state.receipt is None:
                return self._tool_result({"error": "submission_conflict"}, is_error=True)
            return self._tool_result(self._receipt_payload(state.receipt))
        try:
            decoded_payload = _decode_submission_payload(
                session.task_kind,
                arguments[argument_name],
            )
        except (json.JSONDecodeError, ValueError):
            return self._tool_result(
                {
                    "error": "schema_invalid",
                    "issues": [{"path": argument_name, "type": "json_invalid"}],
                },
                is_error=True,
            )
        normalized_payload, normalized_fields = _normalize_submission_payload(
            session.task_kind,
            decoded_payload,
        )
        try:
            envelope = self._build_envelope(session, normalized_payload)
        except ValidationError as exc:
            issues = [
                {
                    "path": ".".join(str(part) for part in error["loc"]),
                    "type": error["type"],
                }
                for error in exc.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            ]
            return self._tool_result(
                {"error": "schema_invalid", "issues": issues},
                is_error=True,
            )
        receipt = GenerationSubmissionReceipt(
            submission_id="prototype-generation-submission-" + secrets.token_hex(16),
            request_hash=request_hash,
            accepted_at=time.time(),
            normalized_fields=normalized_fields,
        )
        state.request_hash = request_hash
        state.receipt = receipt
        state.envelope = envelope
        return self._tool_result(self._receipt_payload(receipt))

    @staticmethod
    def _build_envelope(
        session: GenerationMcpSession,
        raw_payload: object,
    ) -> GenerationArtifactEnvelopeV1:
        identity = {
            "generationContractVersion": 1,
            "jobId": session.job_id,
            "runId": session.run_id,
            "itemId": session.item_id,
            "taskKind": session.task_kind,
            "contextObjectHash": session.context_object_hash,
        }
        if session.task_kind == "generation_blueprint":
            blueprint = GenerationBlueprintV1.model_validate(
                raw_payload, strict=True, by_alias=True, by_name=False
            )
            return GenerationBlueprintEnvelopeV1.model_validate(
                {**identity, "payload": blueprint.model_dump(mode="json", by_alias=True)},
                strict=True,
            )
        if session.task_kind == "generation_foundation":
            foundation = GenerationFoundationV1.model_validate(
                raw_payload, strict=True, by_alias=True, by_name=False
            )
            return GenerationFoundationEnvelopeV1.model_validate(
                {**identity, "payload": foundation.model_dump(mode="json", by_alias=True)},
                strict=True,
            )
        page = GeneratedPageV1.model_validate(
            raw_payload, strict=True, by_alias=True, by_name=False
        )
        return GenerationPageEnvelopeV1.model_validate(
            {**identity, "payload": page.model_dump(mode="json", by_alias=True)},
            strict=True,
        )

    @staticmethod
    def _receipt_payload(receipt: GenerationSubmissionReceipt) -> dict[str, object]:
        return {
            "submissionId": receipt.submission_id,
            "requestHash": receipt.request_hash,
            "acceptedAt": receipt.accepted_at,
            "normalizedFields": list(receipt.normalized_fields),
            "status": "staged",
        }

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


class StructuredPrototypeGenerationMcpError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _decode_submission_payload(
    task_kind: GenerationTaskKind,
    raw_payload: object,
) -> object:
    if task_kind != "generation_page":
        return raw_payload
    if not isinstance(raw_payload, str):
        raise ValueError("generation page payloadJson must be a string")
    return json.loads(raw_payload, parse_constant=_reject_json_constant)


def _normalize_submission_payload(
    task_kind: GenerationTaskKind,
    raw_payload: object,
) -> tuple[object, tuple[str, ...]]:
    if task_kind != "generation_page" or not isinstance(raw_payload, dict):
        return raw_payload, ()
    payload = dict(raw_payload)
    root = payload.get("root")
    if not isinstance(root, dict):
        return payload, ()
    normalized_fields: list[str] = []
    payload["root"] = _normalize_page_node(
        root,
        path="payload.root",
        normalized_fields=normalized_fields,
    )
    return payload, tuple(normalized_fields)


def _normalize_page_node(
    raw_node: dict[object, object],
    *,
    path: str,
    normalized_fields: list[str],
) -> dict[object, object]:
    node = dict(raw_node)
    node_type = node.get("type")
    if node_type == "Stack":
        _normalize_integer_field(node, "gap", path, normalized_fields)
        _normalize_integer_field(node, "padding", path, normalized_fields)
        _normalize_child_nodes(node, path, normalized_fields)
    elif node_type == "Form":
        _normalize_integer_field(node, "gap", path, normalized_fields)
        _normalize_child_nodes(node, path, normalized_fields)
    elif node_type == "Input":
        _normalize_boolean_field(node, "required", path, normalized_fields)
        _normalize_boolean_field(node, "disabled", path, normalized_fields)
    elif node_type == "Button":
        _normalize_boolean_field(node, "disabled", path, normalized_fields)
    elif node_type == "Table":
        _normalize_json_array_field(node, "columns", path, normalized_fields)
    return node


def _normalize_child_nodes(
    node: dict[object, object],
    path: str,
    normalized_fields: list[str],
) -> None:
    _normalize_json_array_field(node, "children", path, normalized_fields)
    children = node.get("children")
    if not isinstance(children, list):
        return
    node["children"] = [
        _normalize_page_node(
            child,
            path=f"{path}.children[{index}]",
            normalized_fields=normalized_fields,
        )
        if isinstance(child, dict)
        else child
        for index, child in enumerate(children)
    ]


def _normalize_integer_field(
    value: dict[object, object],
    field: str,
    path: str,
    normalized_fields: list[str],
) -> None:
    raw = value.get(field)
    if not isinstance(raw, str) or _DECIMAL_INTEGER_RE.fullmatch(raw) is None:
        return
    value[field] = int(raw)
    normalized_fields.append(f"{path}.{field}")


def _normalize_boolean_field(
    value: dict[object, object],
    field: str,
    path: str,
    normalized_fields: list[str],
) -> None:
    raw = value.get(field)
    if raw == "true":
        value[field] = True
    elif raw == "false":
        value[field] = False
    else:
        return
    normalized_fields.append(f"{path}.{field}")


def _normalize_json_array_field(
    value: dict[object, object],
    field: str,
    path: str,
    normalized_fields: list[str],
) -> None:
    raw = value.get(field)
    if isinstance(raw, dict):
        if set(raw) != {"item"} or not isinstance(raw["item"], list):
            return
        parsed = raw["item"]
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(parsed, list):
            return
    else:
        return
    value[field] = parsed
    normalized_fields.append(f"{path}.{field}")


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant is not accepted: {value}")
