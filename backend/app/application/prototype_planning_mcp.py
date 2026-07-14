from __future__ import annotations

import hmac
import json
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from app.application import audit
from app.application.mcp_registry import (
    McpServerDescriptor,
    McpToolDescriptor,
)
from app.application.prototype_planning_service import PrototypePlanError, PrototypePlanService
from app.domain.models import Project
from app.domain.project_evidence import (
    EvidenceLocation,
    ProjectSurfaceManifest,
    PrototypeCandidate,
    source_line_count,
)

PROTOTYPE_PLANNING_MCP_DESCRIPTOR = McpServerDescriptor(
    id="prototype-planning",
    display_name="Prototype Planning",
    description="Discovers project pages and persists the reviewed prototype inventory.",
    owner="prototype",
    scope="plan",
    transport="http",
    version="1.0",
    tools=(
        McpToolDescriptor(
            id="list_discovered_pages",
            description="List deterministic routes and source entry points without source excerpts.",
            risk_level="read",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        McpToolDescriptor(
            id="register_prototype_page",
            description="Persist one code-read page using a candidate ID and supported evidence IDs.",
            risk_level="write",
            input_schema={
                "type": "object",
                "required": ["title", "summary", "brief", "evidence_ids"],
                "properties": {
                    "candidate_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "brief": {"type": "string"},
                    "states": {"type": "array", "items": {"type": "string"}},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "source_paths": {"type": "array", "items": {"type": "string"}},
                    "route_patterns": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
        ),
        McpToolDescriptor(
            id="finalize_prototype_inventory",
            description="Finalize after every deterministic route has been registered.",
            risk_level="write",
            input_schema={
                "type": "object",
                "required": ["project_context"],
                "properties": {"project_context": {"type": "object"}},
                "additionalProperties": False,
            },
        ),
    ),
)


@dataclass(frozen=True)
class PrototypePlanningMcpSession:
    token: str
    plan_id: str

    def claude_config(self, endpoint: str) -> str:
        return json.dumps(
            {
                "mcpServers": {
                    "prototype-planning": {
                        "type": "http",
                        "url": endpoint,
                        "headers": {"X-Prototype-Planning-Token": self.token},
                    }
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass
class _SessionState:
    session: PrototypePlanningMcpSession
    project: Project
    manifest: ProjectSurfaceManifest
    listed: bool = False


class PrototypePlanningMcpService:
    """Plan-scoped MCP tools for Claude's read-only source analysis."""

    descriptor = PROTOTYPE_PLANNING_MCP_DESCRIPTOR

    def __init__(self, plan_service: PrototypePlanService) -> None:
        self.plan_service = plan_service
        self._sessions: dict[str, _SessionState] = {}

    def open_session(
        self, *, project: Project, plan_id: str, manifest: ProjectSurfaceManifest
    ) -> PrototypePlanningMcpSession:
        session = PrototypePlanningMcpSession(token=secrets.token_urlsafe(32), plan_id=plan_id)
        self._sessions[session.token] = _SessionState(
            session=session,
            project=project,
            manifest=manifest,
        )
        return session

    def close_session(self, session: object) -> None:
        if isinstance(session, PrototypePlanningMcpSession):
            self._sessions.pop(session.token, None)

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
                request_id, -32001, "prototype planning MCP session is unavailable"
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
        result = await self._call_tool(state, name, arguments)
        audit.record_mcp_call(
            server_id=self.descriptor.id,
            tool_id=name,
            scope_id=state.session.plan_id,
            task_id=None,
            started=started,
            is_error=result["isError"] is True,
        )
        return 200, self._result(request_id, result)

    async def _call_tool(
        self, state: _SessionState, name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        try:
            if name == "list_discovered_pages":
                state.listed = True
                return self._tool_result(self._compact_manifest(state.manifest))
            if name == "register_prototype_page":
                candidate = self._dynamic_candidate(state, arguments)
                source_candidate = candidate or next(
                    (
                        item
                        for item in state.manifest.candidates
                        if item.candidate_id == arguments.get("candidate_id")
                    ),
                    None,
                )
                planner_payload: dict[str, object] = {
                    key: arguments[key]
                    for key in (
                        "candidate_id",
                        "title",
                        "summary",
                        "brief",
                        "states",
                        "evidence_ids",
                    )
                    if key in arguments
                }
                if source_candidate is not None and "states" not in arguments:
                    planner_payload["states"] = list(source_candidate.states)
                if candidate is not None:
                    planner_payload["candidate_id"] = candidate.candidate_id
                    planner_payload["evidence_ids"] = [
                        evidence.evidence_id for evidence in candidate.evidence
                    ]
                item = await self.plan_service.register_mcp_item(
                    plan_id=state.session.plan_id,
                    manifest=state.manifest,
                    payload=planner_payload,
                    candidate_override=candidate,
                )
                return self._tool_result(
                    {
                        "item_id": item.id,
                        "candidate_id": item.candidate_id,
                        "registered": True,
                    }
                )
            if name == "finalize_prototype_inventory":
                if not state.listed:
                    return self._tool_result(
                        {"error": "list_discovered_pages must be called before finalization"},
                        is_error=True,
                    )
                context = arguments.get("project_context")
                if not isinstance(context, dict):
                    return self._tool_result(
                        {"error": "project_context is required"}, is_error=True
                    )
                missing = await self.plan_service.finalize_mcp_inventory(
                    plan_id=state.session.plan_id,
                    manifest=state.manifest,
                    project_context=context,
                )
                if missing:
                    return self._tool_result(
                        {
                            "finalized": False,
                            "missing_candidate_ids": missing,
                            "instruction": "Read the listed source files and register every missing candidate.",
                        },
                        is_error=True,
                    )
                return self._tool_result({"finalized": True})
            return self._tool_result({"error": "unknown prototype planning tool"}, is_error=True)
        except PrototypePlanError as exc:
            return self._tool_result({"error": str(exc)}, is_error=True)

    @staticmethod
    def _compact_manifest(manifest: ProjectSurfaceManifest) -> dict[str, object]:
        return {
            "repository_fingerprint": manifest.repository_fingerprint,
            "diagnostics": list(manifest.diagnostics),
            "pages": [
                {
                    "candidate_id": candidate.candidate_id,
                    "route_patterns": list(candidate.route_patterns),
                    "package_root": candidate.package_root,
                    "framework_hint": candidate.framework_hint,
                    "primary_source_path": candidate.primary_source_path,
                    "source_paths": list(candidate.source_paths),
                    "layout_paths": list(candidate.layout_paths),
                    "evidence_ids": [evidence.evidence_id for evidence in candidate.evidence],
                    "confidence": candidate.confidence,
                    "diagnostics": list(candidate.diagnostics),
                }
                for candidate in manifest.candidates
            ],
        }

    @staticmethod
    def _dynamic_candidate(
        state: _SessionState, arguments: dict[str, object]
    ) -> PrototypeCandidate | None:
        candidate_id = arguments.get("candidate_id")
        if isinstance(candidate_id, str) and any(
            candidate.candidate_id == candidate_id for candidate in state.manifest.candidates
        ):
            return None
        source_paths = arguments.get("source_paths")
        route_patterns = arguments.get("route_patterns")
        evidence_raw = arguments.get("evidence")
        if (
            not isinstance(source_paths, list)
            or not source_paths
            or not all(isinstance(path, str) and path for path in source_paths)
            or not isinstance(route_patterns, list)
            or not route_patterns
            or not all(isinstance(route, str) and route.startswith("/") for route in route_patterns)
            or not isinstance(evidence_raw, list)
            or not evidence_raw
        ):
            raise PrototypePlanError(
                "non-static Claude discovery requires source_paths, route_patterns, and evidence"
            )
        root = Path(state.project.repo_path).resolve()
        normalized_paths: list[str] = []
        source_hashes: list[str] = []
        for raw_path in source_paths:
            assert isinstance(raw_path, str)
            resolved = (root / raw_path).resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise PrototypePlanError("Claude discovery source path is outside the project")
            relative = resolved.relative_to(root).as_posix()
            normalized_paths.append(relative)
            source_hashes.append(f"{relative}|{sha256(resolved.read_bytes()).hexdigest()}")
        evidence: list[EvidenceLocation] = []
        for raw in evidence_raw:
            if not isinstance(raw, dict):
                raise PrototypePlanError("Claude discovery evidence must be an object")
            path = raw.get("path")
            start_line = raw.get("start_line")
            end_line = raw.get("end_line")
            detail = raw.get("detail", "")
            if (
                not isinstance(path, str)
                or path not in normalized_paths
                or not isinstance(start_line, int)
                or not isinstance(end_line, int)
                or start_line < 1
                or end_line < start_line
                or not isinstance(detail, str)
            ):
                raise PrototypePlanError("Claude discovery evidence is invalid")
            line_count = source_line_count(
                (root / path).read_text(encoding="utf-8", errors="replace")
            )
            if end_line > line_count:
                raise PrototypePlanError(
                    "Claude discovery evidence line is outside the source file"
                )
            evidence.append(
                EvidenceLocation(
                    path=path,
                    start_line=start_line,
                    end_line=end_line,
                    kind="page-source",
                    detail=detail,
                    confidence="medium",
                )
            )
        package_root = str(Path(normalized_paths[0]).parent)
        key = "|".join([*sorted(route_patterns), *sorted(normalized_paths)])
        return PrototypeCandidate(
            candidate_id="claude--" + sha256(key.encode()).hexdigest()[:20],
            title="Claude discovered page",
            route_patterns=tuple(route_patterns),
            surface_kind="web",
            package_root=package_root,
            framework_hint="claude-discovered",
            primary_source_path=normalized_paths[0],
            source_paths=tuple(normalized_paths),
            layout_paths=(),
            evidence=tuple(evidence),
            confidence="medium",
            source_hash="sha256:" + sha256("\n".join(sorted(source_hashes)).encode()).hexdigest(),
        )

    @staticmethod
    def _tools() -> list[dict[str, object]]:
        return PROTOTYPE_PLANNING_MCP_DESCRIPTOR.protocol_tools()

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
