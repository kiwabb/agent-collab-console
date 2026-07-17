from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.project_source_reader import (
    RepositoryBoundary,
    RepositoryBoundaryError,
    RepositoryLimitError,
    RepositoryTextEncodingError,
)
from app.adapters.prototype_object_store import canonical_json_bytes
from app.application import audit
from app.application.mcp_registry import McpServerDescriptor, McpToolDescriptor
from app.application.structured_prototype_generation_contracts import (
    GENERATION_CONTRACT_VERSION,
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
GENERATION_DISCOVERY_RESULT_MAX_BYTES = 64 * 1024
GENERATION_DISCOVERY_LIST_MAX_FILES = 500
GENERATION_DISCOVERY_SEARCH_MAX_MATCHES = 100
GENERATION_DISCOVERY_READ_MAX_LINES = 400
GENERATION_DISCOVERY_SEARCH_MAX_SCAN_FILES = 1_000
GENERATION_DISCOVERY_SEARCH_MAX_SCAN_BYTES = 2_000_000
GENERATION_DISCOVERY_EXCERPT_MAX_CHARS = 400
GENERATION_DISCOVERY_READ_LINE_MAX_CHARS = 1_000
GENERATION_DISCOVERY_SESSION_MAX_CALLS = 128
GENERATION_DISCOVERY_SESSION_MAX_SCAN_FILES = 20_000
GENERATION_DISCOVERY_SESSION_MAX_SCAN_BYTES = 16_000_000
GENERATION_DISCOVERY_SESSION_MAX_RETURNED_BYTES = 4_000_000
GENERATION_DISCOVERY_REPOSITORY_MAX_FILES = 12_000
GENERATION_DISCOVERY_FILE_MAX_BYTES = 100_000
_DECIMAL_INTEGER_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_REPOSITORY_TOOL_IDS = frozenset(
    {
        "list_project_files",
        "search_project_text",
        "read_project_file",
    }
)


class _ListProjectFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(
        default="**",
        min_length=1,
        max_length=512,
        description="Root-relative POSIX glob pattern. Absolute and parent paths are refused.",
    )
    limit: int = Field(default=200, ge=1, le=GENERATION_DISCOVERY_LIST_MAX_FILES)


class _SearchProjectTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=256, pattern=r"^[^\r\n\x00]+$")
    file_pattern: str = Field(
        default="**",
        alias="filePattern",
        min_length=1,
        max_length=512,
        description="Optional root-relative POSIX glob filter.",
    )
    case_sensitive: bool = Field(default=False, alias="caseSensitive")
    limit: int = Field(default=50, ge=1, le=GENERATION_DISCOVERY_SEARCH_MAX_MATCHES)


class _ReadProjectFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        max_length=1_024,
        description="Root-relative POSIX file path. Symlinks are refused.",
    )
    start_line: int = Field(default=1, alias="startLine", ge=1, le=1_000_000)
    line_count: int = Field(
        default=200,
        alias="lineCount",
        ge=1,
        le=GENERATION_DISCOVERY_READ_MAX_LINES,
    )


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
    if task_kind in ("generation_foundation", "generation_page"):
        payload_description = (
            "Complete strict JSON serialization of the generation foundation matching "
            "x-payloadSchema. Encode colors and spacing as arrays and sharedShell as an "
            "object inside this JSON string."
            if task_kind == "generation_foundation"
            else "Complete strict JSON serialization of one generated page matching "
            "x-payloadSchema. Arrays must be encoded inside this JSON string."
        )
        json_input_schema: dict[str, object] = {
            "type": "object",
            "required": ["payloadJson"],
            "properties": {
                "payloadJson": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": GENERATION_MCP_PAYLOAD_MAX_BYTES,
                    "description": payload_description,
                }
            },
            "additionalProperties": False,
            "x-payloadSchema": payload_schema,
        }
        if definitions is not None:
            json_input_schema["$defs"] = definitions
        return json_input_schema
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
    description="Reads one isolated project snapshot and finalizes one generation artifact.",
    owner="prototype",
    scope="task",
    transport="http",
    version="1.1",
    tools=(
        McpToolDescriptor(
            id="get_generation_submission_context",
            description="Read the current task and execution identities required by finalization.",
            risk_level="read",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        McpToolDescriptor(
            id="list_project_files",
            description="List bounded root-relative files from the isolated project snapshot.",
            risk_level="read",
            input_schema=_ListProjectFilesInput.model_json_schema(by_alias=True),
        ),
        McpToolDescriptor(
            id="search_project_text",
            description="Search project text using one bounded literal query.",
            risk_level="read",
            input_schema=_SearchProjectTextInput.model_json_schema(by_alias=True),
        ),
        McpToolDescriptor(
            id="read_project_file",
            description="Read bounded lines from one root-relative non-symlink project file.",
            risk_level="read",
            input_schema=_ReadProjectFileInput.model_json_schema(by_alias=True),
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
    normalized_request_hash: str
    wire_input_hash: str
    scope_fingerprint: str
    envelope_hash: str
    envelope_size: int
    accepted_at: float
    repository_root: str
    resolved_path: str
    path_contained: Literal[True]
    normalized_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "submissionId": self.submission_id,
            "requestHash": self.request_hash,
            "normalizedRequestHash": self.normalized_request_hash,
            "wireInputHash": self.wire_input_hash,
            "scopeFingerprint": self.scope_fingerprint,
            "envelopeHash": self.envelope_hash,
            "envelopeSize": self.envelope_size,
            "acceptedAt": self.accepted_at,
            "repositoryRoot": self.repository_root,
            "resolvedPath": self.resolved_path,
            "pathContained": self.path_contained,
            "normalizedFields": list(self.normalized_fields),
        }


@dataclass(frozen=True, slots=True)
class GenerationMcpSubmissionEvidence:
    project_id: str
    job_id: str
    run_id: str
    item_id: str
    task_id: str
    execution_process_id: str
    task_kind: GenerationTaskKind
    context_object_hash: str
    receipt: GenerationSubmissionReceipt


GenerationSubmissionAcceptedCallback = Callable[[GenerationMcpSubmissionEvidence], Awaitable[None]]


@dataclass(slots=True)
class _SessionState:
    session: GenerationMcpSession
    submission_accepted_callback: GenerationSubmissionAcceptedCallback | None = None
    repository_root: Path | None = None
    execution_process_id: str | None = None
    wire_input_hash: str | None = None
    request_hash: str | None = None
    receipt: GenerationSubmissionReceipt | None = None
    envelope: GenerationArtifactEnvelopeV1 | None = None
    call_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False
    repository_call_count: int = 0
    repository_scan_file_count: int = 0
    repository_scan_byte_count: int = 0
    repository_returned_byte_count: int = 0
    successful_repository_tools: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _GenerationToolOutcome:
    result: dict[str, object]
    failure_evidence: audit.McpCallFailureEvidence | None


class _RepositoryToolError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _RepositoryToolExecution:
    result: dict[str, object]
    scanned_files: int
    scanned_bytes: int


@dataclass(frozen=True, slots=True)
class _RepositoryBudgetReservation:
    scanned_files: int
    scanned_bytes: int
    returned_bytes: int


class _RepositoryCallCancelled(asyncio.CancelledError):
    def __init__(self, execution: _RepositoryToolExecution | None) -> None:
        super().__init__("repository call cancelled")
        self.execution = execution


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
        submission_accepted_callback: GenerationSubmissionAcceptedCallback | None = None,
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
        self._sessions[session.token] = _SessionState(
            session=session,
            submission_accepted_callback=submission_accepted_callback,
        )
        return session

    def bind_execution_process(
        self,
        session: GenerationMcpSession,
        execution_process_id: str,
    ) -> None:
        state = self._sessions.get(session.token)
        if state is None or state.session != session:
            raise StructuredPrototypeGenerationMcpError(
                "submission_scope_violation",
                "structured prototype generation MCP session is unavailable",
            )
        if state.repository_root is None:
            raise StructuredPrototypeGenerationMcpError(
                "repository_scope_missing",
                "structured prototype generation repository scope is not bound",
            )
        if (
            state.execution_process_id is not None
            and state.execution_process_id != execution_process_id
        ):
            raise StructuredPrototypeGenerationMcpError(
                "submission_scope_violation",
                "structured prototype generation MCP process identity changed",
            )
        state.execution_process_id = execution_process_id

    def bind_wire_input(
        self,
        session: GenerationMcpSession,
        *,
        task_id: str,
        execution_process_id: str,
        wire_input_hash: str,
    ) -> None:
        state = self._sessions.get(session.token)
        if (
            state is None
            or state.session != session
            or task_id != session.task_id
            or state.execution_process_id != execution_process_id
            or state.repository_root is None
        ):
            raise StructuredPrototypeGenerationMcpError(
                "submission_scope_violation",
                "structured prototype generation wire-input identity is inconsistent",
            )
        if re.fullmatch(r"sha256:[0-9a-f]{64}", wire_input_hash) is None:
            raise StructuredPrototypeGenerationMcpError(
                "submission_scope_violation",
                "structured prototype generation wire-input hash is invalid",
            )
        if state.wire_input_hash is not None and state.wire_input_hash != wire_input_hash:
            raise StructuredPrototypeGenerationMcpError(
                "submission_scope_violation",
                "structured prototype generation wire-input identity changed",
            )
        state.wire_input_hash = wire_input_hash

    def bind_repository_root(
        self,
        session: GenerationMcpSession,
        *,
        task_id: str,
        worktree_root: Path,
    ) -> None:
        state = self._sessions.get(session.token)
        if state is None or state.session != session or task_id != session.task_id:
            raise StructuredPrototypeGenerationMcpError(
                "repository_scope_violation",
                "structured prototype generation repository identity is inconsistent",
            )
        if state.execution_process_id is not None:
            raise StructuredPrototypeGenerationMcpError(
                "repository_scope_violation",
                "structured prototype generation repository scope was bound too late",
            )
        try:
            boundary = RepositoryBoundary.from_repo_path(str(worktree_root))
        except RepositoryBoundaryError as exc:
            raise StructuredPrototypeGenerationMcpError(
                "repository_scope_violation",
                "structured prototype generation repository scope is unavailable",
            ) from exc
        if state.repository_root is not None and state.repository_root != boundary.root:
            raise StructuredPrototypeGenerationMcpError(
                "repository_scope_violation",
                "structured prototype generation repository scope changed",
            )
        state.repository_root = boundary.root

    async def close_session(self, session: GenerationMcpSession) -> None:
        state = self._sessions.get(session.token)
        if state is None:
            return
        async with state.call_lock:
            state.closed = True
            if self._sessions.get(session.token) is state:
                self._sessions.pop(session.token)

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
            allowed_tools = {
                "get_generation_submission_context",
                "list_project_files",
                "search_project_text",
                "read_project_file",
                state.session.allowed_tool,
            }
            tools = [
                tool for tool in self.descriptor.protocol_tools() if tool["name"] in allowed_tools
            ]
            return 200, self._result(request_id, {"tools": tools})
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
        try:
            async with state.call_lock:
                if state.closed:
                    return 401, self._error(
                        request_id,
                        -32001,
                        "structured prototype generation MCP session is unavailable",
                    )
                outcome = await self._call_tool(state, name, arguments)
        except asyncio.CancelledError:
            audit.record_mcp_call(
                server_id=self.descriptor.id,
                tool_id=name,
                scope_id=state.session.item_id,
                task_id=state.session.task_id,
                started=started,
                is_error=True,
                failure_evidence=audit.McpCallFailureEvidence(
                    code="repository_call_cancelled",
                    issues=(),
                ),
            )
            raise
        audit.record_mcp_call(
            server_id=self.descriptor.id,
            tool_id=name,
            scope_id=state.session.item_id,
            task_id=state.session.task_id,
            started=started,
            is_error=outcome.result["isError"] is True,
            failure_evidence=outcome.failure_evidence,
        )
        return 200, self._result(request_id, outcome.result)

    async def _call_tool(
        self,
        state: _SessionState,
        name: str,
        arguments: dict[str, object],
    ) -> _GenerationToolOutcome:
        session = state.session
        if state.repository_root is None or state.execution_process_id is None:
            return self._tool_result({"error": "repository_scope_missing"}, is_error=True)
        if name == "get_generation_submission_context":
            if arguments:
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
        if name in _REPOSITORY_TOOL_IDS:
            if state.receipt is not None:
                return self._tool_result({"error": "submission_already_finalized"}, is_error=True)
            try:
                reservation = self._reserve_repository_budget(state, name)
                execution = await self._run_repository_tool(
                    state,
                    name,
                    arguments,
                    reservation,
                )
            except _RepositoryCallCancelled as exc:
                if exc.execution is not None:
                    self._settle_repository_budget(state, reservation, exc.execution)
                raise
            except ValidationError as exc:
                return self._tool_result(
                    {
                        "error": "schema_invalid",
                        "issues": [
                            {
                                "path": _validation_issue_path(error["loc"], error["type"]),
                                "type": error["type"],
                            }
                            for error in exc.errors(
                                include_url=False,
                                include_context=False,
                                include_input=False,
                            )
                        ],
                    },
                    is_error=True,
                )
            except _RepositoryToolError as exc:
                return self._tool_result({"error": exc.code}, is_error=True)
            except RepositoryLimitError:
                return self._tool_result(
                    {"error": "repository_scan_quota_exceeded"},
                    is_error=True,
                )
            except RepositoryTextEncodingError:
                return self._tool_result({"error": "invalid_utf8_refused"}, is_error=True)
            except RepositoryBoundaryError:
                return self._tool_result(
                    {"error": "repository_scope_violation"},
                    is_error=True,
                )
            self._settle_repository_budget(state, reservation, execution)
            state.successful_repository_tools.add(name)
            return self._tool_result(execution.result)
        if name != session.allowed_tool:
            return self._tool_result({"error": "submission_scope_violation"}, is_error=True)
        argument_name = "payload" if session.task_kind == "generation_blueprint" else "payloadJson"
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
                    "path": _validation_issue_path(error["loc"], error["type"]),
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
        if session.task_kind == "generation_blueprint" and not _REPOSITORY_TOOL_IDS.issubset(
            state.successful_repository_tools
        ):
            return self._tool_result(
                {"error": "repository_provenance_incomplete"},
                is_error=True,
            )
        repository_root = state.repository_root
        execution_process_id = state.execution_process_id
        wire_input_hash = state.wire_input_hash
        if repository_root is None or execution_process_id is None:
            return self._tool_result({"error": "repository_scope_missing"}, is_error=True)
        if wire_input_hash is None:
            return self._tool_result({"error": "wire_input_evidence_missing"}, is_error=True)
        try:
            resolved_path = repository_root.resolve(strict=True)
            verified_root = RepositoryBoundary.from_repo_path(str(repository_root)).root
        except (OSError, RepositoryBoundaryError):
            return self._tool_result({"error": "repository_scope_violation"}, is_error=True)
        if resolved_path != verified_root or not resolved_path.is_relative_to(verified_root):
            return self._tool_result({"error": "repository_scope_violation"}, is_error=True)
        normalized_request = {
            argument_name: envelope.payload.model_dump(mode="json", by_alias=True)
        }
        normalized_request_hash = (
            "sha256:" + hashlib.sha256(canonical_json_bytes(normalized_request)).hexdigest()
        )
        envelope_bytes = canonical_json_bytes(envelope.model_dump(mode="json", by_alias=True))
        envelope_hash = "sha256:" + hashlib.sha256(envelope_bytes).hexdigest()
        scope_fingerprint = (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "projectId": session.project_id,
                        "jobId": session.job_id,
                        "runId": session.run_id,
                        "itemId": session.item_id,
                        "taskId": session.task_id,
                        "executionProcessId": execution_process_id,
                        "taskKind": session.task_kind,
                        "contextObjectHash": session.context_object_hash,
                        "wireInputHash": wire_input_hash,
                        "repositoryRoot": str(verified_root),
                        "pathContained": True,
                    }
                )
            ).hexdigest()
        )
        receipt = GenerationSubmissionReceipt(
            submission_id="prototype-generation-submission-" + secrets.token_hex(16),
            request_hash=request_hash,
            normalized_request_hash=normalized_request_hash,
            wire_input_hash=wire_input_hash,
            scope_fingerprint=scope_fingerprint,
            envelope_hash=envelope_hash,
            envelope_size=len(envelope_bytes),
            accepted_at=time.time(),
            repository_root=str(verified_root),
            resolved_path=str(resolved_path),
            path_contained=True,
            normalized_fields=normalized_fields,
        )
        submission_evidence = GenerationMcpSubmissionEvidence(
            project_id=session.project_id,
            job_id=session.job_id,
            run_id=session.run_id,
            item_id=session.item_id,
            task_id=session.task_id,
            execution_process_id=execution_process_id,
            task_kind=session.task_kind,
            context_object_hash=session.context_object_hash,
            receipt=receipt,
        )
        if state.submission_accepted_callback is not None:
            try:
                await state.submission_accepted_callback(submission_evidence)
            except Exception:  # Caller-owned durable persistence boundary.
                return self._tool_result(
                    {"error": "submission_evidence_unavailable"},
                    is_error=True,
                )
        state.request_hash = request_hash
        state.receipt = receipt
        state.envelope = envelope
        return self._tool_result(self._receipt_payload(receipt))

    @staticmethod
    def _reserve_repository_budget(
        state: _SessionState,
        name: str,
    ) -> _RepositoryBudgetReservation:
        if state.repository_call_count >= GENERATION_DISCOVERY_SESSION_MAX_CALLS:
            raise _RepositoryToolError("repository_call_quota_exceeded")
        remaining_files = (
            GENERATION_DISCOVERY_SESSION_MAX_SCAN_FILES - state.repository_scan_file_count
        )
        remaining_bytes = (
            GENERATION_DISCOVERY_SESSION_MAX_SCAN_BYTES - state.repository_scan_byte_count
        )
        remaining_returned = (
            GENERATION_DISCOVERY_SESSION_MAX_RETURNED_BYTES - state.repository_returned_byte_count
        )
        if remaining_files <= 0:
            raise _RepositoryToolError("repository_scan_quota_exceeded")
        if remaining_returned < GENERATION_DISCOVERY_RESULT_MAX_BYTES:
            raise _RepositoryToolError("repository_return_quota_exceeded")
        if name == "list_project_files":
            scanned_files = min(
                GENERATION_DISCOVERY_REPOSITORY_MAX_FILES,
                remaining_files,
            )
            scanned_bytes = 0
        elif name == "search_project_text":
            if remaining_bytes <= 0:
                raise _RepositoryToolError("repository_scan_quota_exceeded")
            scanned_files = min(
                GENERATION_DISCOVERY_REPOSITORY_MAX_FILES,
                remaining_files,
            )
            scanned_bytes = min(
                GENERATION_DISCOVERY_SEARCH_MAX_SCAN_BYTES,
                remaining_bytes,
            )
        elif name == "read_project_file":
            if remaining_bytes <= 0:
                raise _RepositoryToolError("repository_scan_quota_exceeded")
            scanned_files = 1
            scanned_bytes = min(GENERATION_DISCOVERY_FILE_MAX_BYTES, remaining_bytes)
        else:
            raise _RepositoryToolError("repository_scope_violation")
        reservation = _RepositoryBudgetReservation(
            scanned_files=scanned_files,
            scanned_bytes=scanned_bytes,
            returned_bytes=GENERATION_DISCOVERY_RESULT_MAX_BYTES,
        )
        state.repository_call_count += 1
        state.repository_scan_file_count += reservation.scanned_files
        state.repository_scan_byte_count += reservation.scanned_bytes
        state.repository_returned_byte_count += reservation.returned_bytes
        return reservation

    @staticmethod
    def _settle_repository_budget(
        state: _SessionState,
        reservation: _RepositoryBudgetReservation,
        execution: _RepositoryToolExecution,
    ) -> None:
        returned_bytes = len(
            json.dumps(
                execution.result,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if (
            execution.scanned_files > reservation.scanned_files
            or execution.scanned_bytes > reservation.scanned_bytes
            or returned_bytes > reservation.returned_bytes
        ):
            raise RuntimeError("repository discovery exceeded its reserved budget")
        state.repository_scan_file_count -= reservation.scanned_files - execution.scanned_files
        state.repository_scan_byte_count -= reservation.scanned_bytes - execution.scanned_bytes
        state.repository_returned_byte_count -= reservation.returned_bytes - returned_bytes

    @staticmethod
    async def _run_repository_tool(
        state: _SessionState,
        name: str,
        arguments: dict[str, object],
        reservation: _RepositoryBudgetReservation,
    ) -> _RepositoryToolExecution:
        thread_task = asyncio.create_task(
            asyncio.to_thread(
                StructuredPrototypeGenerationMcpService._call_repository_tool,
                state,
                name,
                arguments,
                reservation.scanned_files,
                reservation.scanned_bytes,
            )
        )
        try:
            return await asyncio.shield(thread_task)
        except asyncio.CancelledError as cancelled:
            execution: _RepositoryToolExecution | None = None
            while not thread_task.done():
                try:
                    execution = await asyncio.shield(thread_task)
                except asyncio.CancelledError:
                    continue
                except Exception:  # Repository boundary already lost its caller.
                    break
            if thread_task.done() and not thread_task.cancelled():
                with suppress(Exception):  # Result drained; cancellation stays authoritative.
                    execution = thread_task.result()
            raise _RepositoryCallCancelled(execution) from cancelled

    @staticmethod
    def _call_repository_tool(
        state: _SessionState,
        name: str,
        arguments: dict[str, object],
        scan_file_limit: int,
        scan_byte_limit: int,
    ) -> _RepositoryToolExecution:
        root = state.repository_root
        process_id = state.execution_process_id
        if root is None or process_id is None:
            raise RepositoryBoundaryError("repository scope is unavailable")
        resolved_root = RepositoryBoundary.from_repo_path(str(root)).root
        boundary = RepositoryBoundary(
            root=resolved_root,
            max_files=scan_file_limit,
            max_file_bytes=GENERATION_DISCOVERY_FILE_MAX_BYTES,
            max_total_bytes=scan_byte_limit,
        )
        identity: dict[str, object] = {
            "taskId": state.session.task_id,
            "executionProcessId": process_id,
            "itemId": state.session.item_id,
            "taskKind": state.session.task_kind,
            "contextObjectHash": state.session.context_object_hash,
        }
        if name == "list_project_files":
            list_request = _ListProjectFilesInput.model_validate(
                arguments,
                strict=True,
                by_alias=True,
                by_name=False,
            )
            return _list_project_files(boundary, list_request, identity)
        if name == "search_project_text":
            search_request = _SearchProjectTextInput.model_validate(
                arguments,
                strict=True,
                by_alias=True,
                by_name=False,
            )
            return _search_project_text(boundary, search_request, identity)
        if name == "read_project_file":
            read_request = _ReadProjectFileInput.model_validate(
                arguments,
                strict=True,
                by_alias=True,
                by_name=False,
            )
            return _read_project_file(boundary, read_request, identity)
        raise RepositoryBoundaryError("repository tool is unavailable")

    @staticmethod
    def _build_envelope(
        session: GenerationMcpSession,
        raw_payload: object,
    ) -> GenerationArtifactEnvelopeV1:
        identity = {
            "generationContractVersion": GENERATION_CONTRACT_VERSION,
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
        return {**receipt.to_dict(), "status": "staged"}

    @staticmethod
    def _tool_result(
        value: dict[str, object],
        *,
        is_error: bool = False,
    ) -> _GenerationToolOutcome:
        failure_evidence = (
            StructuredPrototypeGenerationMcpService._failure_evidence(value) if is_error else None
        )
        return _GenerationToolOutcome(
            result={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            value,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                ],
                "isError": is_error,
            },
            failure_evidence=failure_evidence,
        )

    @staticmethod
    def _failure_evidence(value: dict[str, object]) -> audit.McpCallFailureEvidence:
        code = value["error"]
        if not isinstance(code, str):
            raise TypeError("generation MCP error code must be a string")
        raw_issues = value.get("issues", [])
        if not isinstance(raw_issues, list):
            raise TypeError("generation MCP validation issues must be a list")
        issues: list[audit.McpValidationIssueEvidence] = []
        for raw_issue in raw_issues:
            if not isinstance(raw_issue, dict):
                raise TypeError("generation MCP validation issue must be an object")
            path = raw_issue["path"]
            issue_type = raw_issue["type"]
            if not isinstance(path, str) or not isinstance(issue_type, str):
                raise TypeError("generation MCP validation issue fields must be strings")
            issues.append(audit.McpValidationIssueEvidence(path=path, issue_type=issue_type))
        return audit.McpCallFailureEvidence(code=code, issues=tuple(issues))

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


def _list_project_files(
    boundary: RepositoryBoundary,
    request: _ListProjectFilesInput,
    identity: dict[str, object],
) -> _RepositoryToolExecution:
    pattern = _safe_project_pattern(request.pattern)
    records = _repository_file_records(boundary)
    matched = [record for record in records if _matches_project_pattern(record["path"], pattern)]
    files: list[dict[str, object]] = []
    content_bytes = 0
    for record in matched[: request.limit]:
        record_bytes = len(canonical_json_bytes(record))
        if content_bytes + record_bytes > 48 * 1024:
            break
        files.append(record)
        content_bytes += record_bytes
    reasons: list[str] = []
    if len(matched) > request.limit:
        reasons.append("result_limit")
    if len(files) < min(len(matched), request.limit):
        reasons.append("result_byte_limit")
    result = _finalize_discovery_result(
        {
            "context": identity,
            "pattern": pattern,
            "files": files,
            "returnedCount": len(files),
            "matchedCount": len(matched),
            "truncated": bool(reasons),
            "truncationReasons": reasons,
        }
    )
    return _RepositoryToolExecution(result=result, scanned_files=len(records), scanned_bytes=0)


def _search_project_text(
    boundary: RepositoryBoundary,
    request: _SearchProjectTextInput,
    identity: dict[str, object],
) -> _RepositoryToolExecution:
    pattern = _safe_project_pattern(request.file_pattern)
    records = _repository_file_records(boundary)
    candidates = [record for record in records if _matches_project_pattern(record["path"], pattern)]
    reasons: list[str] = []
    if len(candidates) > GENERATION_DISCOVERY_SEARCH_MAX_SCAN_FILES:
        reasons.append("scan_file_limit")
    matches: list[dict[str, object]] = []
    matched_count = 0
    scanned_files = 0
    scanned_bytes = 0
    skipped_files = 0
    matcher = re.compile(re.escape(request.query), 0 if request.case_sensitive else re.IGNORECASE)
    for record in candidates[:GENERATION_DISCOVERY_SEARCH_MAX_SCAN_FILES]:
        size = record["sizeBytes"]
        if not isinstance(size, int):
            raise RepositoryBoundaryError("repository file size is invalid")
        if size > boundary.max_file_bytes:
            skipped_files += 1
            if "file_size_limit" not in reasons:
                reasons.append("file_size_limit")
            continue
        if scanned_bytes + size > min(
            GENERATION_DISCOVERY_SEARCH_MAX_SCAN_BYTES,
            boundary.max_total_bytes,
        ):
            reasons.append("scan_byte_limit")
            break
        path = record["path"]
        if not isinstance(path, str):
            raise RepositoryBoundaryError("repository file path is invalid")
        scanned_files += 1
        scanned_bytes += size
        try:
            content = boundary.read_text(boundary.resolve_relative(path))
        except RepositoryTextEncodingError:
            skipped_files += 1
            if "invalid_utf8" not in reasons:
                reasons.append("invalid_utf8")
            continue
        if "\x00" in content:
            skipped_files += 1
            if "binary_file" not in reasons:
                reasons.append("binary_file")
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            for found in matcher.finditer(line):
                matched_count += 1
                if len(matches) >= request.limit:
                    continue
                excerpt, excerpt_start, excerpt_truncated = _match_excerpt(line, found.start())
                candidate = {
                    "path": path,
                    "line": line_number,
                    "column": found.start() + 1,
                    "excerptStartColumn": excerpt_start + 1,
                    "text": excerpt,
                    "textTruncated": excerpt_truncated,
                }
                if len(canonical_json_bytes([*matches, candidate])) > 48 * 1024:
                    if "result_byte_limit" not in reasons:
                        reasons.append("result_byte_limit")
                    continue
                matches.append(candidate)
    if matched_count > request.limit:
        reasons.append("result_limit")
    result = _finalize_discovery_result(
        {
            "context": identity,
            "query": request.query,
            "filePattern": pattern,
            "caseSensitive": request.case_sensitive,
            "matches": matches,
            "returnedCount": len(matches),
            "matchedCount": matched_count,
            "scannedFileCount": scanned_files,
            "scannedByteCount": scanned_bytes,
            "skippedFileCount": skipped_files,
            "truncated": bool(reasons),
            "truncationReasons": reasons,
        }
    )
    return _RepositoryToolExecution(
        result=result,
        scanned_files=len(records),
        scanned_bytes=scanned_bytes,
    )


def _read_project_file(
    boundary: RepositoryBoundary,
    request: _ReadProjectFileInput,
    identity: dict[str, object],
) -> _RepositoryToolExecution:
    normalized_path = _safe_project_path(request.path)
    resolved = boundary.resolve_relative(normalized_path)
    if not resolved.is_file():
        raise RepositoryBoundaryError("repository path is not a file")
    try:
        file_size = resolved.stat().st_size
    except OSError as exc:
        raise RepositoryBoundaryError("repository file metadata is unavailable") from exc
    if file_size > boundary.max_file_bytes:
        raise _RepositoryToolError("file_size_limit")
    if file_size > boundary.max_total_bytes:
        raise _RepositoryToolError("repository_scan_quota_exceeded")
    content = boundary.read_text(resolved)
    if "\x00" in content:
        raise _RepositoryToolError("binary_file_refused")
    all_lines = content.splitlines()
    start_index = request.start_line - 1
    requested_lines = all_lines[start_index : start_index + request.line_count]
    lines: list[dict[str, object]] = []
    reasons: list[str] = []
    for offset, line in enumerate(requested_lines):
        text = line[:GENERATION_DISCOVERY_READ_LINE_MAX_CHARS]
        line_truncated = len(text) != len(line)
        candidate = {
            "line": request.start_line + offset,
            "text": text,
            "textTruncated": line_truncated,
        }
        if len(canonical_json_bytes([*lines, candidate])) > 48 * 1024:
            reasons.append("result_byte_limit")
            break
        if line_truncated and "line_length_limit" not in reasons:
            reasons.append("line_length_limit")
        lines.append(candidate)
    next_start_line = request.start_line + len(lines)
    eof = next_start_line > len(all_lines)
    if not eof and "result_byte_limit" not in reasons:
        reasons.append("line_count_limit")
    result = _finalize_discovery_result(
        {
            "context": identity,
            "path": normalized_path,
            "fileSizeBytes": file_size,
            "startLine": request.start_line,
            "requestedLineCount": request.line_count,
            "returnedLineCount": len(lines),
            "totalLineCount": len(all_lines),
            "lines": lines,
            "nextStartLine": None if eof else next_start_line,
            "eof": eof,
            "truncated": bool(reasons),
            "truncationReasons": reasons,
        }
    )
    return _RepositoryToolExecution(result=result, scanned_files=1, scanned_bytes=file_size)


def _repository_file_records(boundary: RepositoryBoundary) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in boundary.iter_files():
        relative = boundary.relative_path(path)
        resolved = boundary.resolve_relative(relative)
        if not resolved.is_file():
            raise RepositoryBoundaryError("repository entry changed during discovery")
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            raise RepositoryBoundaryError("repository file metadata is unavailable") from exc
        records.append({"path": relative, "sizeBytes": size})
    return sorted(records, key=lambda record: str(record["path"]))


def _safe_project_pattern(pattern: str) -> str:
    normalized = pattern
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or "\x00" in normalized or "\\" in normalized:
        raise RepositoryBoundaryError("project file pattern is unsafe")
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts:
        raise RepositoryBoundaryError("project file pattern escapes root")
    return normalized


def _safe_project_path(path: str) -> str:
    normalized = path
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized == ".":
        raise RepositoryBoundaryError("project file path is invalid")
    relative = PurePosixPath(normalized)
    if (
        "\x00" in normalized
        or "\\" in normalized
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise RepositoryBoundaryError("project file path escapes root")
    return normalized


def _matches_project_pattern(path: object, pattern: str) -> bool:
    if not isinstance(path, str):
        raise RepositoryBoundaryError("repository file path is invalid")
    candidate = pattern
    while True:
        if PurePosixPath(path).match(candidate) or fnmatch.fnmatchcase(path, candidate):
            return True
        if candidate.startswith("**/"):
            candidate = candidate[3:]
            continue
        if "/**/" in candidate:
            candidate = candidate.replace("/**/", "/", 1)
            continue
        return False


def _match_excerpt(line: str, match_start: int) -> tuple[str, int, bool]:
    if len(line) <= GENERATION_DISCOVERY_EXCERPT_MAX_CHARS:
        return line, 0, False
    half = GENERATION_DISCOVERY_EXCERPT_MAX_CHARS // 2
    excerpt_start = max(0, match_start - half)
    excerpt_start = min(excerpt_start, len(line) - GENERATION_DISCOVERY_EXCERPT_MAX_CHARS)
    return (
        line[excerpt_start : excerpt_start + GENERATION_DISCOVERY_EXCERPT_MAX_CHARS],
        excerpt_start,
        True,
    )


def _finalize_discovery_result(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    hash_value = dict(value)
    hash_value.pop("context", None)
    result["resultHash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(hash_value)).hexdigest()
    if len(canonical_json_bytes(result)) > GENERATION_DISCOVERY_RESULT_MAX_BYTES:
        raise _RepositoryToolError("result_byte_limit")
    return result


def _validation_issue_path(location: tuple[int | str, ...], issue_type: str) -> str:
    parts = [str(part) for part in location]
    if issue_type == "extra_forbidden" and parts:
        parts[-1] = "__extra__"
    return ".".join(parts) or "$"


def _decode_submission_payload(
    task_kind: GenerationTaskKind,
    raw_payload: object,
) -> object:
    if task_kind == "generation_blueprint":
        return raw_payload
    if not isinstance(raw_payload, str):
        raise ValueError("generation artifact payloadJson must be a string")
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
    elif node_type == "Grid":
        _normalize_integer_field(node, "columns", path, normalized_fields)
        _normalize_integer_field(node, "gap", path, normalized_fields)
        _normalize_integer_field(node, "padding", path, normalized_fields)
        _normalize_grid_column_overrides(node, path, normalized_fields)
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


def _normalize_grid_column_overrides(
    node: dict[object, object],
    path: str,
    normalized_fields: list[str],
) -> None:
    _normalize_json_array_field(node, "columnOverrides", path, normalized_fields)
    overrides = node.get("columnOverrides")
    if not isinstance(overrides, list):
        return
    for index, raw_override in enumerate(overrides):
        if not isinstance(raw_override, dict):
            continue
        override_path = f"{path}.columnOverrides[{index}]"
        _normalize_integer_field(raw_override, "minWidth", override_path, normalized_fields)
        _normalize_integer_field(raw_override, "columns", override_path, normalized_fields)


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
