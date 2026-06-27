from __future__ import annotations  # noqa: I001

from pathlib import Path
from dataclasses import asdict, is_dataclass
from typing import Any

from app.application.process_runtime_common import is_unusable_result_text
from app.domain.models import CodexTask, SubAgentResult, WorkflowNode


def build_subagent_result(
    *,
    task: CodexTask,
    node: WorkflowNode,
    doc: Any | None = None,
) -> SubAgentResult:
    """Build the full structured result envelope for Conductor and mesh handoffs."""
    artifact_paths = _artifact_paths(doc)
    return SubAgentResult(
        task_id=task.id,
        node_key=node.node_key,
        role=task.role,
        agent_id=node.agent_id,
        status=_result_status(task, doc),
        summary="" if is_unusable_result_text(task.result) else (task.result or ""),
        artifact_json=_artifact_json(doc),
        artifact_markdown=_artifact_markdown(artifact_paths),
        artifact_paths=artifact_paths,
        files_changed=_files_changed(doc),
        qa_commands=_qa_commands(doc),
        clarification_question=_string_attr(doc, "clarification_question"),
        critique=_critique(doc),
        duration_s=_duration_s(task),
        retry_count=node.retries,
        max_retries=node.max_retries,
        review_comment_in=task.review_comment,
        caller_node_key=None,
    )


def _artifact_paths(doc: Any | None) -> list[str]:
    written_files = getattr(doc, "written_files", None) or []
    paths: list[str] = []
    for item in written_files:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if path:
            paths.append(str(path))
    return paths


def _result_status(task: CodexTask, doc: Any | None) -> str:
    payload = _artifact_json(doc)
    if isinstance(payload, dict):
        status = payload.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
    status = getattr(doc, "status", None)
    if isinstance(status, str) and status.strip():
        return status.strip()
    return task.status


def _artifact_json(doc: Any | None) -> dict | None:
    if doc is None:
        return None
    if hasattr(doc, "model_dump"):
        payload = doc.model_dump()
        return payload if isinstance(payload, dict) else None
    if hasattr(doc, "dict"):
        payload = doc.dict()
        return payload if isinstance(payload, dict) else None
    if is_dataclass(doc):
        return asdict(doc)
    return None


def _artifact_markdown(paths: list[str]) -> str | None:
    for path in paths:
        p = Path(path)
        if p.suffix.lower() != ".md" or not p.exists():
            continue
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def _files_changed(doc: Any | None) -> list[str]:
    changed = getattr(doc, "changed_files", None)
    if isinstance(changed, list):
        return [str(item) for item in changed]
    payload = _artifact_json(doc)
    if isinstance(payload, dict) and isinstance(payload.get("changed_files"), list):
        return [str(item) for item in payload["changed_files"]]
    return []


def _qa_commands(doc: Any | None) -> list[dict] | None:
    execution_results = getattr(doc, "execution_results", None)
    if isinstance(execution_results, list):
        return [item for item in execution_results if isinstance(item, dict)]
    payload = _artifact_json(doc)
    if isinstance(payload, dict) and isinstance(payload.get("commands_run"), list):
        return [{"command": str(command)} for command in payload["commands_run"]]
    return None


def _critique(doc: Any | None) -> dict | None:
    critique = _string_attr(doc, "architect_critique")
    if not critique:
        return None
    return {"architect_critique": critique}


def _string_attr(doc: Any | None, name: str) -> str | None:
    value = getattr(doc, name, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _duration_s(task: CodexTask) -> float:
    if not task.created_at or not task.updated_at:
        return 0.0
    return max((task.updated_at - task.created_at).total_seconds(), 0.0)
