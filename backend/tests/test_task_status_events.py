from __future__ import annotations

from datetime import datetime

from app.application.task_status_events import build_task_status_event
from app.domain.models import CodexTask


def test_build_task_status_event_includes_shared_correlation_fields():
    task = CodexTask(
        id="task-1",
        session_id="workspace-1",
        project_id="project-1",
        issue_id="issue-1",
        phase="operations",
        title="Generate Startup Scripts",
        prompt="Generate scripts",
        role="operations_engineer",
        status="running",
        task_kind="project_script_suggestion",
        last_execution_process_id="ep-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    event = build_task_status_event(task, "failed", result="boom")

    assert event == {
        "type": "task_status",
        "task_id": "task-1",
        "project_id": "project-1",
        "issue_id": "issue-1",
        "workspace_id": "workspace-1",
        "session_id": "workspace-1",
        "role": "operations_engineer",
        "task_kind": "project_script_suggestion",
        "status": "failed",
        "execution_process_id": "ep-1",
        "result": "boom",
    }
