from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path

from app.application.process_runtime_common import is_unusable_result_text
from app.domain.models import CodexTask, SubAgentResult, WorkflowNode
from app.json_safety import object_dict_or_none


def build_subagent_result(
    *,
    task: CodexTask,
    node: WorkflowNode,
    doc: object | None = None,
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


def _artifact_paths(doc: object | None) -> list[str]:
    written_files = getattr(doc, "written_files", None) or []
    paths: list[str] = []
    if not isinstance(written_files, list):
        return paths
    for item in written_files:
        file_info = object_dict_or_none(item)
        if file_info is None:
            continue
        path = file_info.get("path")
        if path:
            paths.append(str(path))
    return paths


def _result_status(task: CodexTask, doc: object | None) -> str:
    payload = _artifact_json(doc)
    if isinstance(payload, dict):
        status = payload.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
    status = getattr(doc, "status", None)
    if isinstance(status, str) and status.strip():
        return status.strip()
    return task.status


def _artifact_json(doc: object | None) -> dict[str, object] | None:
    if doc is None:
        return None
    model_dump = getattr(doc, "model_dump", None)
    if callable(model_dump):
        payload = model_dump()
        return object_dict_or_none(payload)
    legacy_dict = getattr(doc, "dict", None)
    if callable(legacy_dict):
        payload = legacy_dict()
        return object_dict_or_none(payload)
    if is_dataclass(doc) and not isinstance(doc, type):
        return object_dict_or_none(asdict(doc))
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


def _files_changed(doc: object | None) -> list[str]:
    changed = getattr(doc, "changed_files", None)
    if isinstance(changed, list):
        return [str(item) for item in changed]
    payload = _artifact_json(doc)
    if payload is not None:
        changed_files = payload.get("changed_files")
        if isinstance(changed_files, list):
            return [str(item) for item in changed_files]
    return []


def _qa_commands(doc: object | None) -> list[dict[str, object]] | None:
    execution_results = getattr(doc, "execution_results", None)
    if isinstance(execution_results, list):
        commands: list[dict[str, object]] = []
        for item in execution_results:
            command = object_dict_or_none(item)
            if command is not None:
                commands.append(command)
        return commands
    payload = _artifact_json(doc)
    if payload is not None:
        commands_run = payload.get("commands_run")
        if isinstance(commands_run, list):
            return [{"command": str(command)} for command in commands_run]
    return None


def _critique(doc: object | None) -> dict[str, object] | None:
    critique = _string_attr(doc, "architect_critique")
    if not critique:
        return None
    return {"architect_critique": critique}


def _string_attr(doc: object | None, name: str) -> str | None:
    value = getattr(doc, name, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _duration_s(task: CodexTask) -> float:
    if not task.created_at or not task.updated_at:
        return 0.0
    return max((task.updated_at - task.created_at).total_seconds(), 0.0)
