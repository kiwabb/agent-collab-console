from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.application.prototype_service import PrototypeError, RuntimePrototypeEvidence
from app.bootstrap import prototype_service
from app.json_safety import parse_json_object

router = APIRouter(prefix="/api")
MAX_CANDIDATE_QUERY_TEXT_CHARS = 1_200


def _to_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\n" + f"data: {json.dumps(data)}\n\n"


def _serialize_stream_event(event: str, data: object) -> str:
    return _to_event(event, data if isinstance(data, dict) else {})


def _parse_runtime_evidence(items: list[str] | None) -> dict[str, RuntimePrototypeEvidence]:
    evidence_by_candidate: dict[str, RuntimePrototypeEvidence] = {}
    for item in items or []:
        candidate_key, sep, raw_json = item.partition("\t")
        if not sep or not candidate_key or not raw_json.strip():
            continue
        payload = parse_json_object(raw_json)
        if payload is None:
            continue
        evidence = RuntimePrototypeEvidence.from_payload(payload)
        if evidence is not None:
            evidence_by_candidate[candidate_key] = evidence
    return evidence_by_candidate


def _parse_candidate_text_map(items: list[str] | None) -> dict[str, str]:
    """Parse candidate-scoped text query params with a bounded value size."""
    values: dict[str, str] = {}
    for item in items or []:
        candidate_key, sep, value = item.partition("\t")
        if sep and candidate_key and value.strip():
            values[candidate_key] = value.strip()[:MAX_CANDIDATE_QUERY_TEXT_CHARS]
    return values


@router.get("/projects/{project_id}/prototypes")
async def list_prototypes(project_id: str) -> object:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    # Confirm project exists.
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    return await prototype_service.list_for_project(project_id)


@router.post("/projects/{project_id}/prototypes", status_code=201)
async def create_prototype(project_id: str, body: dict[str, object]) -> object:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    # Keep behavior deterministic for missing project.
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    title = str(body.get("title") or "").strip()
    brief = str(body.get("brief") or "").strip()
    if not brief:
        raise HTTPException(status_code=400, detail="brief is required")
    return await prototype_service.create(project_id, title, brief)


@router.get("/projects/{project_id}/prototypes/code-candidates")
async def list_prototype_code_candidates(project_id: str) -> object:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    try:
        return await prototype_service.list_code_candidates(project_id)
    except PrototypeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/prototypes/{prototype_id}")
async def get_prototype(prototype_id: str) -> object:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    try:
        return await prototype_service.get_with_versions(prototype_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/prototypes/{prototype_id}/versions/{version_no}")
async def get_prototype_version(prototype_id: str, version_no: int) -> dict[str, object]:
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
async def delete_prototype(prototype_id: str) -> dict[str, str]:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    try:
        await prototype_service.delete(prototype_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": prototype_id}


@router.get("/prototypes/{prototype_id}/stream")
async def stream_prototype(
    prototype_id: str, instruction: str | None = None
) -> StreamingResponse:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")

    try:
        await prototype_service.get(prototype_id)
    except PrototypeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_iter() -> AsyncIterator[str]:
        try:
            async for ev in prototype_service.stream_events(prototype_id, instruction):
                yield _serialize_stream_event(ev.event, ev.data)
                if ev.event in {"done", "error"}:
                    return
        except Exception as exc:
            yield _to_event("error", {"message": str(exc)})

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@router.get("/projects/{project_id}/prototypes/generate-from-code/stream")
async def generate_prototypes_from_code(
    project_id: str,
    candidate_id: list[str] | None = Query(default=None),
    candidate_instruction: list[str] | None = Query(default=None),
    candidate_brief_override: list[str] | None = Query(default=None),
    runtime_evidence: list[str] | None = Query(default=None),
    use_runtime_evidence: bool = False,
    runtime_base_url: str | None = None,
    instruction: str | None = None,
) -> StreamingResponse:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    candidate_instructions = _parse_candidate_text_map(candidate_instruction)
    candidate_brief_overrides = _parse_candidate_text_map(candidate_brief_override)
    runtime_evidence_by_candidate = _parse_runtime_evidence(runtime_evidence)

    async def event_iter() -> AsyncIterator[str]:
        async for ev in prototype_service.generate_all_from_code_stream(
            project_id,
            candidate_ids=candidate_id,
            instruction=instruction,
            candidate_instructions=candidate_instructions,
            candidate_brief_overrides=candidate_brief_overrides,
            runtime_evidence_by_candidate=runtime_evidence_by_candidate,
            use_runtime_evidence=use_runtime_evidence,
            runtime_base_url=runtime_base_url,
        ):
            yield _serialize_stream_event(ev.event, ev.data)

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@router.get("/projects/{project_id}/prototypes/regenerate-all/stream")
async def regenerate_all_prototypes(project_id: str) -> StreamingResponse:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    async def event_iter() -> AsyncIterator[str]:
        async for ev in prototype_service.regenerate_all_stream(project_id):
            yield _serialize_stream_event(ev.event, ev.data)

    return StreamingResponse(event_iter(), media_type="text/event-stream")
