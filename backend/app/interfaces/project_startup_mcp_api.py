from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.application.mcp_registry import MCP_PROTOCOL_VERSION
from app.bootstrap import project_startup_mcp_service

router = APIRouter(prefix="/api")


@router.post("/internal/project-startup-mcp")
async def project_startup_mcp(request: Request) -> Response:
    if project_startup_mcp_service is None:
        return JSONResponse(
            status_code=503,
            content={"error": "project startup MCP unavailable"},
        )
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})
    status, body = await project_startup_mcp_service.handle(
        token=request.headers.get("X-Project-Startup-Token"),
        payload=payload,
    )
    if body is None:
        return Response(status_code=status)
    return JSONResponse(
        status_code=status,
        content=body,
        headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
    )
