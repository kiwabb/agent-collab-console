from __future__ import annotations

import ipaddress
import json
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from app.application.external_prototype_agent_contracts import CreateExternalAgentPairingV1
from app.application.external_prototype_agent_mcp import ExternalPrototypeAgentMcpHandler
from app.application.external_prototype_agent_service import (
    MCP_PATH,
    ExternalPrototypeAgentError,
    ExternalPrototypeAgentService,
)

logger = logging.getLogger(__name__)

MAX_MCP_REQUEST_BYTES = 1_048_576
PAIRING_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")

router = APIRouter()


def get_external_prototype_agent_service() -> ExternalPrototypeAgentService:
    from app.bootstrap import external_prototype_agent_service

    if external_prototype_agent_service is None:
        raise ExternalPrototypeAgentError(
            "external_agent_unavailable",
            "external prototype Agent integration is unavailable",
            retryable=True,
        )
    return external_prototype_agent_service


ExternalAgentServiceDependency = Annotated[
    ExternalPrototypeAgentService,
    Depends(get_external_prototype_agent_service),
]


@router.post("/api/external-prototype-agent/pairings")
async def create_external_agent_pairing(
    pairing_request: CreateExternalAgentPairingV1,
    service: ExternalAgentServiceDependency,
) -> JSONResponse:
    try:
        issued = await service.create_pairing(pairing_request)
    except ExternalPrototypeAgentError as exc:
        return _application_error(exc)
    pairing = issued.pairing
    return JSONResponse(
        status_code=201,
        content={
            "protocolVersion": pairing.protocol_version,
            "pairingId": pairing.id,
            "projectId": pairing.project_id,
            "documentId": pairing.document_id,
            "agentKind": pairing.agent_kind,
            "permissions": list(pairing.permissions),
            "skillVersion": pairing.skill_version,
            "expiresAt": pairing.expires_at.isoformat(),
            "bearerToken": issued.bearer_token,
            "mcpUrl": issued.mcp_url,
            "skillPackagePath": issued.skill_package_path,
            "installManifest": issued.install_manifest,
        },
    )


@router.delete("/api/external-prototype-agent/pairings/{pairing_id}")
async def revoke_external_agent_pairing(
    pairing_id: str,
    service: ExternalAgentServiceDependency,
) -> JSONResponse:
    if not pairing_id or len(pairing_id) > 128:
        return JSONResponse(status_code=400, content={"detail": "pairing_id_invalid"})
    try:
        pairing = await service.revoke_pairing(pairing_id)
    except ExternalPrototypeAgentError as exc:
        return _application_error(exc)
    return JSONResponse(
        content={
            "pairingId": pairing.id,
            "status": pairing.status,
            "revokedAt": pairing.revoked_at.isoformat() if pairing.revoked_at else None,
        }
    )


@router.get("/api/external-prototype-agent/audit-events")
async def list_external_agent_audit_events(
    service: ExternalAgentServiceDependency,
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=128)],
    document_id: Annotated[str, Query(alias="documentId", min_length=1, max_length=128)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> JSONResponse:
    events = await service.list_audit_events(project_id, document_id, limit=limit)
    return JSONResponse(
        content={
            "items": [
                {
                    "id": event.id,
                    "pairingId": event.pairing_id,
                    "projectId": event.project_id,
                    "documentId": event.document_id,
                    "eventKind": event.event_kind,
                    "toolId": event.tool_id,
                    "requestHash": event.request_hash,
                    "outcome": event.outcome,
                    "errorCode": event.error_code,
                    "durationMs": event.duration_ms,
                    "occurredAt": event.occurred_at.isoformat(),
                }
                for event in events
            ]
        }
    )


@router.post(MCP_PATH)
async def external_prototype_agent_mcp(
    request: Request,
    service: ExternalAgentServiceDependency,
) -> Response:
    if not _is_loopback_peer(request.client.host if request.client else None):
        return _mcp_http_error(None, "loopback_required", status_code=403)
    bearer_token = _bearer_token(request.headers.get("authorization"))
    if bearer_token is None:
        return _mcp_http_error(None, "pairing_token_invalid", status_code=401)
    payload, parse_error = await _read_mcp_payload(request)
    if parse_error is not None:
        return parse_error
    try:
        pairing = await service.authorize_pairing(bearer_token)
    except ExternalPrototypeAgentError as exc:
        status_code = 403 if exc.code == "tool_not_allowed" else 401
        return _mcp_http_error(_request_id(payload), exc.code, status_code=status_code)

    handler = ExternalPrototypeAgentMcpHandler(service)
    try:
        dispatched = await handler.handle(pairing, payload)
    except Exception as exc:
        # This is the HTTP/JSON-RPC boundary; never expose internal exception text.
        logger.error("External prototype Agent MCP dispatch failed", exc_info=exc)
        return _mcp_http_error(_request_id(payload), "internal_error", status_code=500)
    if dispatched.body is None:
        return Response(status_code=dispatched.status_code)
    return JSONResponse(status_code=dispatched.status_code, content=dispatched.body)


async def _read_mcp_payload(request: Request) -> tuple[object, JSONResponse | None]:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/json":
        return None, _mcp_http_error(None, "content_type_invalid", status_code=415)
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            return None, _mcp_http_error(None, "content_length_invalid", status_code=400)
        if declared_length < 0 or declared_length > MAX_MCP_REQUEST_BYTES:
            return None, _mcp_http_error(None, "request_too_large", status_code=413)
    body = await request.body()
    if len(body) > MAX_MCP_REQUEST_BYTES:
        return None, _mcp_http_error(None, "request_too_large", status_code=413)
    try:
        return json.loads(body), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _mcp_http_error(None, "parse_error", status_code=400, rpc_code=-32700)


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or PAIRING_TOKEN_PATTERN.fullmatch(token) is None:
        return None
    return token


def _is_loopback_peer(host: str | None) -> bool:
    if host == "localhost":
        return True
    if host is None:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _request_id(payload: object) -> str | int | None:
    if not isinstance(payload, dict):
        return None
    request_id = payload.get("id")
    if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
        return None
    return request_id


def _mcp_http_error(
    request_id: str | int | None,
    code: str,
    *,
    status_code: int,
    rpc_code: int = -32001,
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": rpc_code,
                "message": code,
                "data": {"code": code},
            },
        },
    )


def _application_error(error: ExternalPrototypeAgentError) -> JSONResponse:
    status_codes = {
        "external_agent_unavailable": 503,
        "prototype_core_unavailable": 503,
        "pairing_missing": 404,
        "pairing_scope_invalid": 404,
        "pairing_secret_unrecoverable": 409,
        "pairing_state_conflict": 409,
        "submission_conflict": 409,
        "mcp_url_invalid": 400,
    }
    return JSONResponse(
        status_code=status_codes.get(error.code, 500),
        content={"detail": error.code, "retryable": error.retryable},
    )
