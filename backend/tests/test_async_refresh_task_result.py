from datetime import datetime

import pytest

from app.application.codex_task_runner import CodexTaskRunner
from app.application.process_runtime_common import AsyncProcessEntry, BaseProcessRuntime
from app.domain.models import CodexTask, CodexSession, ExecutionProcess


class StoreStub:
    def __init__(self, task: CodexTask, workspace: CodexSession):
        self.task = task
        self.workspace = workspace
        self.processes: dict[str, ExecutionProcess] = {}

    async def save_codex_task(self, task: CodexTask):
        self.task = task.model_copy(deep=True)

    async def load_codex_task(self, task_id: str):
        if task_id == self.task.id:
            return self.task
        return None

    async def save_execution_process(self, process: ExecutionProcess):
        self.processes[process.id] = process

    async def update_execution_process_status(self, process_id: str, status: str, exit_code=None, completed_at=None):
        process = self.processes[process_id]
        process.status = status
        process.exit_code = exit_code
        process.completed_at = completed_at
        process.updated_at = completed_at or datetime.now()
        self.processes[process_id] = process

    async def load_codex_workspace(self, workspace_id: str):
        if workspace_id == self.workspace.id:
            return self.workspace
        return None

    async def save_codex_workspace(self, workspace: CodexSession):
        self.workspace = workspace.model_copy(deep=True)

    async def save_codex_task_message(self, message):
        return None

    async def load_runtime_catalog(self):
        return None

    async def save_runtime_catalog(self, catalog):
        pass


class EventBusStub:
    def __init__(self):
        self.events = []

    async def append(self, event):
        self.events.append(event)


class MockManager:
    async def write_input_async(self, *args, **kwargs):
        return "done"


@pytest.mark.asyncio
async def test_codex_task_runner_awaits_async_refresh_callback():
    now = datetime.now()
    task = CodexTask(
        id="task-1",
        session_id="workspace-1",
        issue_id="issue-1",
        title="PM task",
        prompt="write prd",
        role="product_manager",
        executor="codex",
        status="pending",
        workspace_path="/tmp/workspace",
        created_at=now,
        updated_at=now,
    )
    workspace = CodexSession(
        id="workspace-1",
        title="Workspace",
        cwd="/tmp/workspace",
        created_at=now,
        last_active_at=now,
    )
    store = StoreStub(task, workspace)
    bus = EventBusStub()
    refreshed = {"called": False}

    async def refresh_task_result(task):
        refreshed["called"] = True
        task.result = "persisted"

    runner = CodexTaskRunner(
        codex_store=store,
        event_bus=bus,
        process_manager_factory=lambda: MockManager(),
        mock_manager_cls=MockManager,
        refresh_task_result=refresh_task_result,
    )

    process = await runner.start_task_run(task)

    assert refreshed["called"] is True
    assert store.task.result == "persisted"
    assert process.status == "Completed"


class RuntimeStoreStub:
    def __init__(self, task: CodexTask):
        self.task = task
        self.saved_messages = []

    async def load_codex_task(self, task_id: str):
        if task_id == self.task.id:
            return self.task
        return None

    async def save_codex_task(self, task: CodexTask):
        self.task = task.model_copy(deep=True)

    async def update_execution_process_status(self, process_id: str, status: str, exit_code=None, completed_at=None):
        return None

    async def save_codex_task_message(self, message):
        self.saved_messages.append(message)

    async def list_codex_task_messages(self, task_id: str, execution_process_id: str | None = None):
        return []


class RuntimeUnderTest(BaseProcessRuntime):
    def _owns_entry(self, entry) -> bool:
        return True


@pytest.mark.asyncio
async def test_process_runtime_mark_task_done_awaits_async_refresh_callback():
    now = datetime.now()
    task = CodexTask(
        id="task-2",
        session_id="workspace-2",
        issue_id="issue-2",
        title="PM task",
        prompt="write prd",
        role="product_manager",
        executor="codex",
        status="running",
        workspace_path="/tmp/workspace",
        last_execution_process_id="process-2",
        created_at=now,
        updated_at=now,
    )
    store = RuntimeStoreStub(task)
    bus = EventBusStub()
    refreshed = {"called": False}

    async def refresh_task_result(task):
        refreshed["called"] = True
        task.result = "persisted-from-runtime"

    runtime = RuntimeUnderTest(
        codex_store=store,
        log_store=store,
        event_bus=bus,
        refresh_task_result=refresh_task_result,
    )
    entry = AsyncProcessEntry(
        proc=None,
        output_task=None,
        alive=False,
        session_id=task.session_id,
        executor="codex",
        cwd="/tmp/workspace",
        resume_session_id=None,
        result_text='{"ok":true}',
    )

    await runtime._mark_task_done(task.id, entry)

    assert refreshed["called"] is True
    assert store.task.result == "persisted-from-runtime"
