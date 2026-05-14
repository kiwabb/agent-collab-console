from datetime import datetime

import pytest

from app.domain.models import CodexTask, ExecutionProcess, LogEvent
from app.interfaces.codex_ws import ExecutionProcessWorkspaceStreamManager
import app.interfaces.codex_ws as codex_ws_module


class AsyncStoreStub:
    def __init__(self):
        now = datetime.now()
        self.task = CodexTask(
            id="task-1",
            session_id="workspace-1",
            title="Fix websocket status refresh",
            prompt="repro",
            status="running",
            executor="codex",
            last_execution_process_id="process-1",
            created_at=now,
            updated_at=now,
        )
        self.process = ExecutionProcess(
            id="process-1",
            task_id=self.task.id,
            session_id=self.task.session_id,
            status="Running",
            created_at=now,
            updated_at=now,
        )
        self.logs = [
            LogEvent(
                id="log-1",
                session_id=self.task.session_id,
                task_id=self.task.id,
                execution_process_id=self.process.id,
                stream="stdout",
                content="hello",
                created_at=now,
            )
        ]

    async def load_codex_task(self, task_id: str):
        assert task_id == self.task.id
        return self.task

    async def load_execution_process(self, process_id: str):
        assert process_id == self.process.id
        return self.process

    async def list_codex_task_messages(self, task_id: str, execution_process_id: str | None = None):
        assert task_id == self.task.id
        assert execution_process_id == self.process.id
        return []

    async def load_log_events(
        self,
        session_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 1000,
        reverse: bool = False,
    ):
        assert session_id == self.task.session_id
        assert task_id == self.task.id
        assert execution_process_id == self.process.id
        assert limit in {1000, 10000}
        assert reverse is False
        return self.logs

    async def list_execution_processes(self, session_id: str | None = None, task_id: str | None = None):
        assert session_id == self.task.session_id
        assert task_id is None
        return [self.process]

    async def list_execution_process_runtime_rows(self, session_id: str):
        assert session_id == self.task.session_id
        return [(self.process, self.task, [], self.logs)]


@pytest.mark.asyncio
async def test_update_task_status_supports_async_store(monkeypatch):
    store = AsyncStoreStub()
    store.task.status = "failed"
    store.task.result = "rerun failed without artifact"
    manager = ExecutionProcessWorkspaceStreamManager()
    published = []

    async def fake_publish_patch(workspace_id: str, patch: list):
        published.append((workspace_id, patch))

    monkeypatch.setattr(codex_ws_module, "codex_store", store)
    monkeypatch.setattr(manager, "publish_patch", fake_publish_patch)

    await manager.update_task_status(store.task.session_id, store.task.id, "done")

    assert published
    workspace_id, patch = published[0]
    assert workspace_id == store.task.session_id
    assert patch[0]["path"] == f"/execution_processes/{store.process.id}"
    assert patch[0]["value"]["task_id"] == store.task.id
    assert patch[0]["value"]["title"] == store.task.title
    assert patch[0]["value"]["logs"][0]["content"] == "hello"
    pending_events = manager._pending_events[store.task.session_id]
    assert pending_events[-1]["type"] == "task_status"
    assert pending_events[-1]["status"] == "failed"
    assert pending_events[-1]["result"] == "rerun failed without artifact"


@pytest.mark.asyncio
async def test_get_state_supports_async_runtime_rows(monkeypatch):
    store = AsyncStoreStub()
    manager = ExecutionProcessWorkspaceStreamManager()

    monkeypatch.setattr(codex_ws_module, "codex_store", store)

    state = await manager.get_state(store.task.session_id)

    process_payload = state["execution_processes"][store.process.id]
    assert process_payload["id"] == store.process.id
    assert process_payload["task_id"] == store.task.id
    assert process_payload["title"] == store.task.title
    assert process_payload["logs"][0]["id"] == "log-1"
