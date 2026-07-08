from __future__ import annotations


def build_task_status_event(
    task: object,
    status: str | None = None,
    *,
    execution_process_id: str | None = None,
    **extra: object,
) -> dict[str, object]:
    """Build the shared event-bus payload for Codex task status changes."""
    resolved_status = status if status is not None else getattr(task, "status", None)
    resolved_execution_process_id = (
        execution_process_id
        if execution_process_id is not None
        else getattr(task, "last_execution_process_id", None)
    )
    event: dict[str, object] = {
        "type": "task_status",
        "task_id": getattr(task, "id", None),
        "project_id": getattr(task, "project_id", None),
        "issue_id": getattr(task, "issue_id", None),
        "workspace_id": getattr(task, "session_id", None),
        "session_id": getattr(task, "session_id", None),
        "role": getattr(task, "role", None),
        "task_kind": getattr(task, "task_kind", None),
        "status": resolved_status,
        "execution_process_id": resolved_execution_process_id,
        "trace_id": getattr(task, "trace_id", None),
        "span_id": getattr(task, "span_id", None),
        "parent_span_id": getattr(task, "parent_span_id", None),
    }
    event.update(extra)
    return event
