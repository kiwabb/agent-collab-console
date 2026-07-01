from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.application.prototype_service import PrototypeError
from app.bootstrap import prototype_service


router = APIRouter(prefix="/api")


def _to_event(event: str, data: dict) -> str:
    return f"event: {event}\n" + f"data: {json.dumps(data)}\n\n"


def _serialize_stream_event(event, data) -> str:
    return _to_event(event, data if isinstance(data, dict) else {})


@router.get("/projects/{project_id}/prototypes")
async def list_prototypes(project_id: str):
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    # Confirm project exists.
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    return await prototype_service.list_for_project(project_id)


@router.post("/projects/{project_id}/prototypes", status_code=201)
async def create_prototype(project_id: str, body: dict):
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    # Keep behavior deterministic for missing project.
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    title = (body.get("title") or "").strip()
    brief = (body.get("brief") or "").strip()
    if not brief:
        raise HTTPException(status_code=400, detail="brief is required")
    return await prototype_service.create(project_id, title, brief)


@router.get("/prototypes/{prototype_id}")
async def get_prototype(prototype_id: str):
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    try:
        return await prototype_service.get_with_versions(prototype_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/prototypes/{prototype_id}/versions/{version_no}")
async def get_prototype_version(prototype_id: str, version_no: int):
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    html = await prototype_service.get_version_html(
        prototype_id,
        version_no,
    )
    return {
        "prototype_id": prototype_id,
        "version_no": version_no,
        "html": html,
    }


@router.delete("/prototypes/{prototype_id}")
async def delete_prototype(prototype_id: str):
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    try:
        await prototype_service.delete(prototype_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": prototype_id}


@router.get("/prototypes/{prototype_id}/stream")
async def stream_prototype(prototype_id: str, instruction: str | None = None):
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")

    try:
        await prototype_service.get(prototype_id)
    except PrototypeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_iter():
        try:
            async for ev in prototype_service.stream_events(prototype_id, instruction):
                yield _serialize_stream_event(ev.event, ev.data)
                if ev.event in {"done", "error"}:
                    return
        except Exception as exc:  # noqa: BLE001
            yield _to_event("error", {"message": str(exc)})

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@router.get("/projects/{project_id}/prototypes/regenerate-all/stream")
async def regenerate_all_prototypes(project_id: str):
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    async def event_iter():
        async for ev in prototype_service.regenerate_all_stream(project_id):
            yield _serialize_stream_event(ev.event, ev.data)

    return StreamingResponse(event_iter(), media_type="text/event-stream")
