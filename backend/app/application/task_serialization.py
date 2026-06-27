from __future__ import annotations


def serialize_task_payload(task) -> dict:
    return {
        "id": task.id,
        "session_id": task.session_id,
        "issue_id": task.issue_id,
        "phase": task.phase,
        "title": task.title,
        "prompt": task.prompt,
        "role": task.role,
        "status": task.status,
        "result": task.result,
        "executor": task.executor,
        "provider": task.provider,
        "model": task.model,
        "parent_task_id": task.parent_task_id,
        "task_kind": task.task_kind,
        "blocked_by_help_id": task.blocked_by_help_id,
        "resume_session_id": task.resume_session_id,
        "workspace_path": task.workspace_path,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }
