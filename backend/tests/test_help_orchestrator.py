from __future__ import annotations

from datetime import datetime

import pytest

from app.application.help_orchestrator import HelpOrchestrator
from app.domain.models import CodexTask, CodexTaskMessage, HelpRequest


class FakeHelpStore:
    def __init__(self):
        self.tasks: dict[str, CodexTask] = {}
        self.help_requests: dict[str, HelpRequest] = {}
        self.messages: list[CodexTaskMessage] = []
        self.execution_process_statuses: list[tuple[str, str]] = []
        self.save_order: list[tuple[str, str, str, str | None]] = []

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def save_codex_task(self, task: CodexTask):
        self.tasks[task.id] = task
        self.save_order.append(("task", task.id, task.status, task.blocked_by_help_id))

    async def save_help_request(self, help_request: HelpRequest):
        self.help_requests[help_request.id] = help_request
        self.save_order.append(("help_request", help_request.id, help_request.status, None))

    async def load_help_request(self, help_request_id: str):
        return self.help_requests.get(help_request_id)

    async def list_help_requests(self, parent_task_id: str):
        return [
            request
            for request in self.help_requests.values()
            if request.parent_task_id == parent_task_id
        ]

    async def save_codex_task_message(self, message: CodexTaskMessage):
        self.messages.append(message)

    async def update_execution_process_status(self, proc_id: str, status: str, **kwargs):
        self.execution_process_statuses.append((proc_id, status))


class FakeEventBus:
    def __init__(self):
        self.events: list[dict] = []

    async def append(self, event: dict):
        self.events.append(event)


class FailingRunner:
    async def start_task_run(self, task: CodexTask, **kwargs):
        raise RuntimeError("runner unavailable")


class RecordingRunner:
    def __init__(self):
        self.started: list[CodexTask] = []

    async def start_task_run(self, task: CodexTask, **kwargs):
        self.started.append(task)


class _ExecutionProcess:
    def __init__(self, process_id: str):
        self.id = process_id


class ReturningRunner:
    def __init__(self, process_id: str = "ep-help"):
        self.process_id = process_id
        self.started: list[CodexTask] = []

    async def start_task_run(self, task: CodexTask, **kwargs):
        self.started.append(task)
        return _ExecutionProcess(self.process_id)


def _parent_task(**overrides) -> CodexTask:
    base = dict(
        id="parent-1",
        session_id="session-1",
        project_id="project-1",
        issue_id="issue-1",
        phase="development",
        title="Parent",
        prompt="Do work",
        role="engineer",
        executor="codex",
        status="running",
        result=None,
        task_kind="normal",
        workspace_path="/tmp/workspace",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    base.update(overrides)
    return CodexTask(**base)


@pytest.mark.asyncio
async def test_request_help_start_failure_marks_child_help_and_parent_terminal():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(last_execution_process_id="proc-parent")
    await store.save_codex_task(parent)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    with pytest.raises(RuntimeError):
        await orchestrator.request_help(
            parent_task_id=parent.id,
            target_executor="claude",
            title="Need help",
            prompt="Please investigate",
        )

    updated_parent = await store.load_codex_task(parent.id)
    child = next(task for task in store.tasks.values() if task.id != parent.id)
    help_request = next(iter(store.help_requests.values()))
    assert updated_parent.status == "ready_to_resume"
    assert updated_parent.blocked_by_help_id is None
    assert child.status == "failed"
    assert child.project_id == parent.project_id
    assert child.issue_id == parent.issue_id
    assert child.phase == parent.phase
    assert child.role == "help:claude"
    assert "runner unavailable" in (child.result or "")
    assert help_request.status == "failed"
    assert help_request.continuation_payload["error"]["code"] == "help_child_start_failed"
    assert any(event.get("type") == "help_failed" for event in bus.events)
    parent_status = [event for event in bus.events if event.get("task_id") == parent.id]
    assert any(event.get("status") == "ready_to_resume" for event in parent_status)
    assert ("task", parent.id, "ready_to_resume", None) in store.save_order
    assert ("help_request", help_request.id, "failed", None) in store.save_order
    assert store.save_order.index(("task", parent.id, "ready_to_resume", None)) < store.save_order.index(
        ("help_request", help_request.id, "failed", None)
    )


@pytest.mark.asyncio
async def test_request_help_reconciles_unlocked_running_help_before_rejecting_new_request():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(status="running", blocked_by_help_id=None)
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="running",
        blocked_by_help_id="help-1",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status="running",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    runner = RecordingRunner()
    orchestrator = HelpOrchestrator(store, bus, runner)

    with pytest.raises(ValueError, match="already has an unresolved help request"):
        await orchestrator.request_help(
            parent_task_id=parent.id,
            target_executor="gemini",
            title="Second help",
            prompt="Please help too",
        )

    updated_parent = await store.load_codex_task(parent.id)
    assert updated_parent.status == "waiting_for_help"
    assert updated_parent.blocked_by_help_id == help_request.id
    assert runner.started == []
    assert any(
        event.get("type") == "task_status"
        and event.get("task_id") == parent.id
        and event.get("status") == "waiting_for_help"
        for event in bus.events
    )


@pytest.mark.asyncio
async def test_request_help_persists_started_child_running_status_event():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(last_execution_process_id="proc-parent")
    await store.save_codex_task(parent)
    runner = ReturningRunner("ep-help")
    orchestrator = HelpOrchestrator(store, bus, runner)

    help_request = await orchestrator.request_help(
        parent_task_id=parent.id,
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
    )

    child = await store.load_codex_task(help_request.child_task_id)
    assert child.status == "running"
    assert child.last_execution_process_id == "ep-help"
    event = next(
        event
        for event in bus.events
        if event.get("type") == "task_status" and event.get("task_id") == child.id
    )
    assert event["status"] == "running"
    assert event["execution_process_id"] == "ep-help"
    assert event["project_id"] == parent.project_id
    assert event["issue_id"] == parent.issue_id
    assert event["role"] == "help:claude"
    assert event["task_kind"] == "help_child"


@pytest.mark.asyncio
async def test_request_help_completes_unlocked_terminal_help_then_rejects_non_running_parent():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(status="running", blocked_by_help_id=None)
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="done",
        result="old useful findings",
        blocked_by_help_id="help-1",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status="running",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    runner = RecordingRunner()
    orchestrator = HelpOrchestrator(store, bus, runner)

    with pytest.raises(ValueError, match="must be running"):
        await orchestrator.request_help(
            parent_task_id=parent.id,
            target_executor="gemini",
            title="Second help",
            prompt="Please help too",
        )

    old_help = await store.load_help_request(help_request.id)
    updated_parent = await store.load_codex_task(parent.id)
    assert old_help.status == "completed"
    assert updated_parent.status == "ready_to_resume"
    assert updated_parent.blocked_by_help_id is None
    assert runner.started == []


@pytest.mark.asyncio
async def test_complete_help_request_auto_resume_failure_falls_back_to_ready_to_resume():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(
        status="waiting_for_help",
        blocked_by_help_id="help-1",
        resume_session_id="resume-session",
        resume_message_id="resume-message",
    )
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="done",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status="running",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    result = await orchestrator.complete_help_request(
        help_request.id,
        child_status="done",
        child_result="Useful findings",
    )

    updated_parent = await store.load_codex_task(parent.id)
    updated_request = await store.load_help_request(help_request.id)
    assert result.id == help_request.id
    assert updated_parent.status == "ready_to_resume"
    assert updated_parent.blocked_by_help_id is None
    assert updated_request.status == "resume_failed"
    assert updated_request.continuation_payload["resume_error"]["code"] == "parent_auto_resume_failed"
    assert store.messages
    assert "Useful findings" in store.messages[-1].content
    assert any(
        event.get("type") == "task_status"
        and event.get("task_id") == parent.id
        and event.get("status") == "ready_to_resume"
        for event in bus.events
    )


@pytest.mark.asyncio
async def test_complete_help_request_saves_parent_ready_before_terminal_request():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(status=" Waiting_For_Help ", blocked_by_help_id="help-1")
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="done",
        result="Useful findings",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status="running",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    store.save_order.clear()
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    await orchestrator.complete_help_request(
        help_request.id,
        child_status="done",
        child_result="Useful findings",
    )

    assert store.save_order[0] == ("task", parent.id, "ready_to_resume", None)
    assert store.save_order[1] == ("help_request", help_request.id, "completed", None)


@pytest.mark.asyncio
async def test_complete_help_request_accepts_running_status_case_and_spaces():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(status="waiting_for_help", blocked_by_help_id="help-1")
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="done",
        result="Useful findings",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status=" Running ",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    await orchestrator.complete_help_request(
        help_request.id,
        child_status="done",
        child_result="Useful findings",
    )

    updated_request = await store.load_help_request(help_request.id)
    assert updated_request.status == "completed"


@pytest.mark.asyncio
async def test_request_help_from_runtime_rejects_workspace_mismatch_without_source_executor():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task()
    await store.save_codex_task(parent)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    with pytest.raises(ValueError, match="workspace"):
        await orchestrator.request_help_from_runtime(
            task_id=parent.id,
            workspace_id="other-session",
            target_executor="claude",
            title="Need help",
            prompt="Please investigate",
        )


@pytest.mark.asyncio
async def test_request_help_rejects_empty_title_or_prompt():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task()
    await store.save_codex_task(parent)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    with pytest.raises(ValueError, match="title"):
        await orchestrator.request_help(
            parent_task_id=parent.id,
            target_executor="claude",
            title="",
            prompt="Please investigate",
        )

    with pytest.raises(ValueError, match="prompt"):
        await orchestrator.request_help(
            parent_task_id=parent.id,
            target_executor="claude",
            title="Need help",
            prompt="   ",
        )


@pytest.mark.asyncio
async def test_complete_help_request_rejects_non_terminal_child_without_parent_mutation():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(status="waiting_for_help", blocked_by_help_id="help-1")
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="running",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status="running",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    with pytest.raises(ValueError, match="not terminal"):
        await orchestrator.complete_help_request(
            help_request.id,
            child_status="done",
            child_result="stale success",
        )

    updated_parent = await store.load_codex_task(parent.id)
    updated_request = await store.load_help_request(help_request.id)
    assert updated_parent.status == "waiting_for_help"
    assert updated_parent.blocked_by_help_id == "help-1"
    assert updated_request.status == "running"


@pytest.mark.asyncio
async def test_complete_help_request_rejects_already_terminal_request():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(status="ready_to_resume")
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="done",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status="consumed",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    with pytest.raises(ValueError, match="already terminal"):
        await orchestrator.complete_help_request(
            help_request.id,
            child_status="done",
            child_result="duplicate",
        )


@pytest.mark.asyncio
async def test_complete_help_request_rejects_parent_not_waiting_for_request():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(status="running", blocked_by_help_id=None)
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="done",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status="running",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    with pytest.raises(ValueError, match="not waiting"):
        await orchestrator.complete_help_request(
            help_request.id,
            child_status="done",
            child_result="duplicate",
        )


@pytest.mark.asyncio
async def test_complete_help_request_uses_persisted_child_result_when_status_is_stale():
    store = FakeHelpStore()
    bus = FakeEventBus()
    parent = _parent_task(status="waiting_for_help", blocked_by_help_id="help-1")
    child = _parent_task(
        id="child-1",
        parent_task_id=parent.id,
        task_kind="help_child",
        executor="claude",
        status="done",
        result="persisted findings",
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id=parent.session_id,
        parent_task_id=parent.id,
        child_task_id=child.id,
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status="running",
        created_at=datetime.now(),
        started_at=datetime.now(),
    )
    await store.save_codex_task(parent)
    await store.save_codex_task(child)
    await store.save_help_request(help_request)
    orchestrator = HelpOrchestrator(store, bus, FailingRunner())

    await orchestrator.complete_help_request(
        help_request.id,
        child_status="failed",
        child_result="stale failure",
    )

    updated_request = await store.load_help_request(help_request.id)
    assert updated_request.continuation_payload["result"]["summary"] == "persisted findings"
