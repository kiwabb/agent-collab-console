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

    async def queue_log_event(self, event):
        return None

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


@pytest.mark.asyncio
async def test_codex_task_runner_clears_stale_result_before_rerun_refresh():
    now = datetime.now()
    task = CodexTask(
        id="task-rerun-1",
        session_id="workspace-1",
        issue_id="issue-1",
        title="PM task",
        prompt="write prd",
        role="product_manager",
        executor="codex",
        status="done",
        result="stale-summary-from-previous-run",
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
    observed = {"result_at_refresh": "unset"}

    async def refresh_task_result(task):
        observed["result_at_refresh"] = task.result
        task.result = "fresh-summary-from-rerun"

    runner = CodexTaskRunner(
        codex_store=store,
        event_bus=bus,
        process_manager_factory=lambda: MockManager(),
        mock_manager_cls=MockManager,
        refresh_task_result=refresh_task_result,
    )

    process = await runner.start_task_run(task, kind="rerun")

    assert observed["result_at_refresh"] is None
    assert store.task.result == "fresh-summary-from-rerun"
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


@pytest.mark.asyncio
async def test_process_runtime_mark_task_done_emits_single_failure_channel_for_refresh_errors():
    now = datetime.now()
    task = CodexTask(
        id="task-3",
        session_id="workspace-3",
        issue_id="issue-3",
        title="PM task",
        prompt="write prd",
        role="product_manager",
        executor="codex",
        status="running",
        workspace_path="/tmp/workspace",
        last_execution_process_id="process-3",
        created_at=now,
        updated_at=now,
    )
    store = RuntimeStoreStub(task)
    bus = EventBusStub()

    async def refresh_task_result(task):
        raise ValueError("ProductManager 返回了无效的 PRD 格式")

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

    assert store.task.status == "failed"
    assert store.task.result == "ProductManager 返回了无效的 PRD 格式"
    log_events = [event for event in bus.events if event.get("type") == "log"]
    assert log_events == []


@pytest.mark.asyncio
async def test_persist_reader_metadata_does_not_overwrite_terminal_failure_reason():
    now = datetime.now()
    task = CodexTask(
        id="task-4",
        session_id="workspace-4",
        issue_id="issue-4",
        title="PM task",
        prompt="write prd",
        role="product_manager",
        executor="codex",
        status="failed",
        result="actual failure reason",
        workspace_path="/tmp/workspace",
        created_at=now,
        updated_at=now,
    )
    workspace = CodexSession(
        id="workspace-4",
        title="Workspace",
        cwd="/tmp/workspace",
        created_at=now,
        last_active_at=now,
    )
    store = StoreStub(task, workspace)
    runtime = RuntimeUnderTest(
        codex_store=store,
        log_store=store,
        event_bus=EventBusStub(),
        refresh_task_result=None,
    )
    entry = AsyncProcessEntry(
        proc=None,
        output_task=None,
        alive=False,
        session_id=task.session_id,
        executor="codex",
        cwd="/tmp/workspace",
        resume_session_id=None,
        result_text='{"agent":"raw output"}',
    )

    await runtime._persist_reader_metadata(task.session_id, task.id, entry)

    assert store.task.result == "actual failure reason"
