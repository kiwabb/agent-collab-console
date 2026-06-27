from __future__ import annotations

from app.domain.models import CodexTask, CodexTaskMessage, ExecutionProcess, LogEvent


def build_execution_process_view(
    process: ExecutionProcess,
    task: CodexTask | None,
    messages: list[CodexTaskMessage],
    logs: list[LogEvent],
) -> dict:
    # Calculate duration in seconds if both started_at and completed_at are present
    duration_seconds = None
    if process.started_at and process.completed_at:
        duration_seconds = int((process.completed_at - process.started_at).total_seconds())

    return {
        "id": process.id,
        "session_id": process.session_id,
        "task_id": process.task_id,
        "status": process.status,
        "exit_code": process.exit_code,
        "title": task.title if task else process.task_id,
        # Use execution process snapshot fields (actual runtime config)
        "executor": process.executor if process.executor else (task.executor if task else "codex"),
        "provider": process.provider if process.provider else (task.provider if task else None),
        "model": process.model if process.model else (task.model if task else None),
        # Token usage and cost
        "input_tokens": process.input_tokens,
        "output_tokens": process.output_tokens,
        "cache_read_tokens": process.cache_read_tokens,
        "total_cost_usd": process.total_cost_usd,
        "duration_seconds": duration_seconds,
        "workspace_path": task.workspace_path if task else None,
        "resume_session_id": task.resume_session_id if task else None,
        "created_at": process.created_at.isoformat() if process.created_at else None,
        "started_at": process.started_at.isoformat() if process.started_at else None,
        "updated_at": process.updated_at.isoformat() if process.updated_at else None,
        "completed_at": process.completed_at.isoformat() if process.completed_at else None,
        "messages": {
            message.id: {
                "id": message.id,
                "task_id": message.task_id,
                "execution_process_id": message.execution_process_id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            for message in messages
        },
        "logs": [
            {
                "id": log.id,
                "stream": log.stream,
                "content": log.content,
                "task_id": log.task_id,
                "execution_process_id": log.execution_process_id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
