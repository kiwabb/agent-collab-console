import json
import subprocess
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
    def __init__(self, task: CodexTask, workspace: CodexSession | None = None):
        self.task = task
        self.workspace = workspace
        self.saved_messages = []

    async def load_codex_task(self, task_id: str):
        if task_id == self.task.id:
            return self.task
        return None

    async def save_codex_task(self, task: CodexTask):
        self.task = task.model_copy(deep=True)

    async def load_codex_workspace(self, workspace_id: str):
        if self.workspace and workspace_id == self.workspace.id:
            return self.workspace
        return None

    async def save_codex_workspace(self, workspace: CodexSession):
        self.workspace = workspace.model_copy(deep=True)

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
async def test_process_runtime_mark_task_done_handles_empty_result_without_crashing():
    # When a subagent completes but produces no usable result (e.g. its only
    # output was a CLI control payload that got filtered), task.result stays
    # None. _mark_task_done must still complete cleanly — it must not crash on
    # len(None) and must not mis-mark the completed task as failed.
    now = datetime.now()
    task = CodexTask(
        id="task-empty",
        session_id="workspace-empty",
        issue_id="issue-empty",
        title="PM task",
        prompt="write prd",
        role="product_manager",
        executor="codex",
        status="running",
        workspace_path="/tmp/workspace",
        last_execution_process_id="process-empty",
        created_at=now,
        updated_at=now,
    )
    store = RuntimeStoreStub(task)
    bus = EventBusStub()
    refreshed = {"called": False}

    async def refresh_task_result(task):
        refreshed["called"] = True

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
        result_text=None,
    )

    await runtime._mark_task_done(task.id, entry)

    assert store.task.status == "done"
    assert refreshed["called"] is True


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


@pytest.mark.asyncio
async def test_finalize_task_on_reader_exit_salvages_idle_engineer_with_changed_files(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True)

    app_dir = tmp_path / "backend" / "app"
    app_dir.mkdir(parents=True)
    target = app_dir / "sample.py"
    target.write_text("print('before')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=tmp_path, check=True, capture_output=True, text=True)
    target.write_text("print('after')\n", encoding="utf-8")

    now = datetime.now()
    task = CodexTask(
        id="task-engineer-idle",
        session_id="workspace-engineer",
        issue_id="issue-engineer",
        title="Engineer task",
        prompt="implement change",
        role="engineer",
        executor="claude",
        status="running",
        workspace_path=str(tmp_path),
        last_execution_process_id="process-engineer",
        created_at=now,
        updated_at=now,
    )
    workspace = CodexSession(
        id="workspace-engineer",
        title="Recovered Workspace",
        cwd=str(tmp_path),
        created_at=now,
        last_active_at=now,
    )
    store = RuntimeStoreStub(task, workspace)
    bus = EventBusStub()
    captured: dict[str, object] = {}

    async def refresh_task_result(task):
        captured["payload"] = json.loads(task.result)
        task.result = "persisted-fallback-report"

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
        task_id=task.id,
        executor="claude",
        cwd=str(tmp_path),
        resume_session_id=None,
        idle_timed_out=True,
        idle_timeout_seconds=180,
    )

    await runtime._finalize_task_on_reader_exit(task.id, entry)

    assert store.task.status == "done"
    assert store.task.result == "persisted-fallback-report"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["status"] == "partial"
    assert payload["project_name"] == "Recovered Workspace"
    assert "backend/app/sample.py" in payload["changed_files"]


# ── Per-task session identity (shared-session poisoning fix) ──────────────────

from app.application.process_runtime_common import is_workspace_console_task


def test_is_workspace_console_task_discriminator():
    now = datetime.now()

    def mk(**kw):
        base = dict(
            id="t", session_id="ws", title="x", prompt="x",
            created_at=now, updated_at=now,
        )
        base.update(kw)
        return CodexTask(**base)

    # Human workspace-console chat: no issue, normal kind, no parent → shares pointer.
    assert is_workspace_console_task(mk()) is True
    # Conductor role task: belongs to an issue → isolated.
    assert is_workspace_console_task(mk(issue_id="issue-1", role="engineer")) is False
    # Help child / continuation: has a parent → isolated.
    assert is_workspace_console_task(mk(parent_task_id="parent-1")) is False
    # Specialist child: non-normal kind → isolated.
    assert is_workspace_console_task(mk(task_kind="specialist_child")) is False
    assert is_workspace_console_task(None) is False


@pytest.mark.asyncio
async def test_persist_reader_metadata_role_task_does_not_touch_workspace_pointer():
    now = datetime.now()
    task = CodexTask(
        id="role-task", session_id="ws-role", issue_id="issue-role",
        title="Engineer", prompt="impl", role="engineer", executor="claude",
        status="running", workspace_path="/tmp/ws", created_at=now, updated_at=now,
    )
    workspace = CodexSession(
        id="ws-role", title="WS", cwd="/tmp/ws",
        claude_thread_id="stale-shared-session", created_at=now, last_active_at=now,
    )
    store = StoreStub(task, workspace)
    runtime = RuntimeUnderTest(codex_store=store, log_store=store, event_bus=EventBusStub(), refresh_task_result=None)
    entry = AsyncProcessEntry(
        proc=None, output_task=None, alive=False, session_id=task.session_id,
        executor="claude", cwd="/tmp/ws", resume_session_id="role-own-session",
        result_text="real result",
    )
    entry.produced_real_turn = True

    await runtime._persist_reader_metadata(task.session_id, task.id, entry)

    # Session is kept on the task, but the shared workspace pointer is untouched.
    assert store.task.resume_session_id == "role-own-session"
    assert store.workspace.claude_thread_id == "stale-shared-session"


@pytest.mark.asyncio
async def test_persist_reader_metadata_console_task_updates_workspace_pointer():
    now = datetime.now()
    task = CodexTask(  # console task: no issue_id, normal kind, no parent
        id="console-task", session_id="ws-con", title="chat", prompt="hi",
        executor="claude", status="running", created_at=now, updated_at=now,
    )
    workspace = CodexSession(
        id="ws-con", title="WS", cwd="/tmp/ws",
        claude_thread_id="old", created_at=now, last_active_at=now,
    )
    store = StoreStub(task, workspace)
    runtime = RuntimeUnderTest(codex_store=store, log_store=store, event_bus=EventBusStub(), refresh_task_result=None)
    entry = AsyncProcessEntry(
        proc=None, output_task=None, alive=False, session_id=task.session_id,
        executor="claude", cwd="/tmp/ws", resume_session_id="console-session",
        result_text="hello back",
    )
    entry.produced_real_turn = True

    await runtime._persist_reader_metadata(task.session_id, task.id, entry)

    assert store.workspace.claude_thread_id == "console-session"


@pytest.mark.asyncio
async def test_persist_reader_metadata_drops_resume_id_when_no_real_turn():
    now = datetime.now()
    task = CodexTask(
        id="empty-role-task", session_id="ws-empty", issue_id="issue-empty",
        title="Engineer", prompt="impl", role="engineer", executor="claude",
        status="failed", resume_session_id="previous-id",
        workspace_path="/tmp/ws", created_at=now, updated_at=now,
    )
    workspace = CodexSession(id="ws-empty", title="WS", cwd="/tmp/ws", created_at=now, last_active_at=now)
    store = StoreStub(task, workspace)
    runtime = RuntimeUnderTest(codex_store=store, log_store=store, event_bus=EventBusStub(), refresh_task_result=None)
    entry = AsyncProcessEntry(
        proc=None, output_task=None, alive=False, session_id=task.session_id,
        executor="claude", cwd="/tmp/ws",
        resume_session_id="dead-control-only-session",  # captured but no real turn
    )
    # produced_real_turn stays False (control-only run)

    await runtime._persist_reader_metadata(task.session_id, task.id, entry)

    # The dead session must not be carried into a retry → cold start.
    assert store.task.resume_session_id is None


@pytest.mark.asyncio
async def test_issue_task_without_worktree_fails_before_spawn():
    """Issue tasks with no workspace_path must fail immediately, never fall back
    to workspace.cwd (which is the main project directory)."""
    now = datetime.now()
    task = CodexTask(
        id="task-noworktree",
        session_id="ws-1",
        issue_id="issue-42",
        title="Engineer task",
        prompt="implement feature",
        role="engineer",
        executor="codex",
        status="pending",
        workspace_path=None,  # worktree not set up
        created_at=now,
        updated_at=now,
    )
    workspace = CodexSession(
        id="ws-1",
        title="Workspace",
        cwd="/real/main/project",  # main project — must never be used as fallback
        created_at=now,
        last_active_at=now,
    )
    store = StoreStub(task, workspace)
    bus = EventBusStub()
    called_with_cwd = []

    class SpyManager:
        async def write_input_async(self, *args, cwd=None, **kwargs):
            called_with_cwd.append(cwd)
            return "done"

    runner = CodexTaskRunner(
        codex_store=store,
        event_bus=bus,
        process_manager_factory=lambda: SpyManager(),
        mock_manager_cls=SpyManager,
        refresh_task_result=lambda t: None,
    )

    with pytest.raises(ValueError, match="no worktree path"):
        await runner.start_task_run(task)

    assert called_with_cwd == [], "SpyManager must never be called when worktree is missing"
