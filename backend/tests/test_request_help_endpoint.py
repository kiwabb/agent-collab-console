from __future__ import annotations

from datetime import datetime

from app.domain.models import CodexTask


def _task(status: str) -> CodexTask:
    return CodexTask(
        id="task-1",
        session_id="workspace-1",
        project_id="project-1",
        issue_id="issue-1",
        title="Parent Task",
        prompt="Need help",
        role="engineer",
        executor="codex",
        status=status,
        result="current result",
        task_kind="normal",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class _Store:
    def __init__(self, task: CodexTask):
        self.task = task
        self.saved: list[CodexTask] = []

    async def load_codex_task(self, task_id: str):
        return self.task if task_id == self.task.id else None

    async def save_codex_task(self, task: CodexTask):
        self.saved.append(task)
        self.task = task


def test_request_help_rejects_non_running_parent_without_status_mutation(client, monkeypatch):
    import app.interfaces.api as api_module

    task = _task("done")
    store = _Store(task)
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(
        f"/api/codex/tasks/{task.id}/request-help",
        json={"target_executor": "claude"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Task must be running or responding to request help"
    assert task.status == "done"
    assert store.saved == []

