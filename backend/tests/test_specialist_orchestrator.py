"""Tests for Phase 4 specialist orchestrator (P2P mesh calls)."""

import pytest  # noqa: I001
from datetime import datetime
from uuid import uuid4  # noqa: F401

from app.application.specialist_orchestrator import (
    SpecialistOrchestrator,
    SpecialistOrchestratorError,
)
from app.domain.models import CodexTask, AgentMessage


class MockStore:
    """Mock store for testing specialist orchestrator."""

    def __init__(self):
        self.tasks = {}
        self.messages = {}
        self.execution_processes = {}

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def save_codex_task(self, task: CodexTask):
        self.tasks[task.id] = task

    async def list_codex_tasks(self, parent_task_id: str = None):  # noqa: RUF013
        if parent_task_id is None:
            return list(self.tasks.values())
        return [t for t in self.tasks.values() if t.parent_task_id == parent_task_id]

    async def load_workflow_graph_for_issue(self, issue_id: str):
        # Mock graph object
        class MockGraph:
            def __init__(self):
                self.id = f"graph_{issue_id}"

        return MockGraph()

    async def save_agent_message(self, msg: AgentMessage):
        self.messages[msg.id] = msg

    async def update_execution_process_status(self, proc_id: str, status: str, completed_at=None):
        if proc_id in self.execution_processes:
            self.execution_processes[proc_id]["status"] = status
            if completed_at:
                self.execution_processes[proc_id]["completed_at"] = completed_at


class MockEventBus:
    """Mock event bus for testing."""

    def __init__(self):
        self.events = []

    async def append(self, event: dict):
        self.events.append(event)


class MockTaskRunner:
    """Mock task runner for testing."""

    def __init__(self):
        self.started_tasks = []

    async def start_task_run(self, task: CodexTask, **kwargs):
        self.started_tasks.append(task)


@pytest.fixture
def store():
    return MockStore()


@pytest.fixture
def event_bus():
    return MockEventBus()


@pytest.fixture
def task_runner():
    return MockTaskRunner()


@pytest.fixture
def orchestrator(store, event_bus, task_runner):
    return SpecialistOrchestrator(store, event_bus, task_runner)


@pytest.fixture
def parent_task():
    """Create a running Engineer parent task."""
    return CodexTask(
        id="engineer-task-1",
        session_id="session-1",
        project_id="project-1",
        issue_id="issue-1",
        title="Implement feature X",
        prompt="Implement a new authentication module",
        role="engineer",
        executor="claude",
        status="running",
        result=None,
        task_kind="normal",
        workspace_path="/tmp/workspace",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.mark.asyncio
async def test_request_specialist_creates_child_task(orchestrator, store, parent_task):
    """Test that request_specialist creates a specialist child task."""
    await store.save_codex_task(parent_task)

    child = await orchestrator.request_specialist(
        parent_task=parent_task,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review the authentication module for vulnerabilities",
        why="The auth module handles user credentials",
    )

    assert child is not None
    assert child.task_kind == "specialist_child"
    assert child.parent_task_id == parent_task.id
    assert child.role == "specialist:security_reviewer"
    assert "Review the authentication module" in child.prompt


@pytest.mark.asyncio
async def test_request_specialist_pauses_parent(orchestrator, store, parent_task):
    """Test that request_specialist pauses the parent task."""
    await store.save_codex_task(parent_task)

    await orchestrator.request_specialist(
        parent_task=parent_task,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review auth code",
        why="Security concern",
    )

    updated_parent = await store.load_codex_task(parent_task.id)
    assert updated_parent.status == "waiting_for_specialist"


@pytest.mark.asyncio
async def test_request_specialist_emits_events(orchestrator, store, event_bus, parent_task):
    """Test that request_specialist emits proper events."""
    await store.save_codex_task(parent_task)

    await orchestrator.request_specialist(
        parent_task=parent_task,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review code",
        why="Security",
    )

    # Check for specialist_requested event
    specialist_events = [e for e in event_bus.events if e["type"] == "specialist_requested"]
    assert len(specialist_events) > 0
    assert specialist_events[0]["specialist_role"] == "specialist:security_reviewer"


@pytest.mark.asyncio
async def test_request_specialist_invalid_role_key(orchestrator, store, parent_task):
    """Test that invalid specialist role key raises error."""
    await store.save_codex_task(parent_task)

    with pytest.raises(SpecialistOrchestratorError):
        await orchestrator.request_specialist(
            parent_task=parent_task,
            specialist_role_key="invalid_role",  # Missing "specialist:" prefix
            specialist_prompt="Review code",
            why="Test",
        )


@pytest.mark.asyncio
async def test_request_specialist_parent_not_running(orchestrator, store):
    """Test that non-running parent task raises error."""
    parent = CodexTask(
        id="pending-task",
        session_id="session-1",
        issue_id="issue-1",
        title="Task",
        prompt="Prompt",
        role="engineer",
        status="pending",  # Not running!
        task_kind="normal",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await store.save_codex_task(parent)

    with pytest.raises(SpecialistOrchestratorError):
        await orchestrator.request_specialist(
            parent_task=parent,
            specialist_role_key="specialist:security_reviewer",
            specialist_prompt="Review",
            why="Test",
        )


@pytest.mark.asyncio
async def test_request_specialist_mesh_depth_limit(orchestrator, store):
    """Test that specialist children cannot request further specialist calls."""
    specialist_child = CodexTask(
        id="specialist-child-1",
        session_id="session-1",
        issue_id="issue-1",
        title="Security Review",
        prompt="Review code",
        role="specialist:security_reviewer",
        status="running",
        task_kind="specialist_child",  # Already a specialist child!
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await store.save_codex_task(specialist_child)

    with pytest.raises(SpecialistOrchestratorError):
        await orchestrator.request_specialist(
            parent_task=specialist_child,
            specialist_role_key="specialist:performance_reviewer",
            specialist_prompt="Review perf",
            why="Nested call",
        )


@pytest.mark.asyncio
async def test_complete_specialist_request_resumes_parent(orchestrator, store, parent_task):
    """Test that completing specialist request resumes parent task."""
    await store.save_codex_task(parent_task)

    # Create specialist child
    child = await orchestrator.request_specialist(
        parent_task=parent_task,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review code",
        why="Security",
    )

    # Simulate specialist completion
    child.status = "done"
    child.result = "Found 2 potential vulnerabilities in auth module:\n1. Missing rate limiting\n2. No CSRF protection"
    await store.save_codex_task(child)

    # Complete the specialist request
    resumed_parent = await orchestrator.complete_specialist_request(
        specialist_child_task_id=child.id,
        specialist_result_summary=child.result,
    )

    assert resumed_parent.status == "pending"  # Reset to pending for re-run
    assert "[SPECIALIST RESULT" in resumed_parent.review_comment
    assert "vulnerabilities" in resumed_parent.review_comment


@pytest.mark.asyncio
async def test_complete_specialist_request_injects_result(orchestrator, store, parent_task):
    """Test that specialist result is properly injected into parent."""
    await store.save_codex_task(parent_task)

    child = await orchestrator.request_specialist(
        parent_task=parent_task,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review",
        why="Security",
    )

    child.status = "done"
    child.result = "Security review: All good"
    await store.save_codex_task(child)

    result_summary = "Security review findings: No critical vulnerabilities found"
    resumed_parent = await orchestrator.complete_specialist_request(
        specialist_child_task_id=child.id,
        specialist_result_summary=result_summary,
    )

    assert "Security review findings" in resumed_parent.review_comment
    assert "specialist:security_reviewer" in resumed_parent.review_comment


@pytest.mark.asyncio
async def test_complete_specialist_request_creates_agent_message(orchestrator, store, parent_task):
    """Test that specialist result creates an AgentMessage in the feed."""
    await store.save_codex_task(parent_task)

    child = await orchestrator.request_specialist(
        parent_task=parent_task,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review",
        why="Security",
    )

    child.status = "done"
    child.result = "Security findings"
    await store.save_codex_task(child)

    await orchestrator.complete_specialist_request(
        specialist_child_task_id=child.id,
        specialist_result_summary="Security findings",
    )

    # Check that an AgentMessage was created
    messages = list(store.messages.values())
    specialist_messages = [m for m in messages if m.message_type == "specialist_result"]
    assert len(specialist_messages) > 0
    assert specialist_messages[0].from_node_key == "specialist:security_reviewer"
    assert specialist_messages[0].to_node_key == "engineer"


@pytest.mark.asyncio
async def test_unresolved_specialist_request_detection(orchestrator, store, parent_task):
    """Test that unresolved specialist requests prevent new calls."""
    await store.save_codex_task(parent_task)

    # Create first specialist request
    child1 = await orchestrator.request_specialist(
        parent_task=parent_task,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review",
        why="Security",
    )
    child1.status = "running"  # Still running
    await store.save_codex_task(child1)

    # Try to create second specialist request while first is pending
    with pytest.raises(SpecialistOrchestratorError):
        await orchestrator.request_specialist(
            parent_task=parent_task,
            specialist_role_key="specialist:performance_reviewer",
            specialist_prompt="Review perf",
            why="Performance",
        )


@pytest.mark.asyncio
async def test_specialist_child_task_properties(orchestrator, store, parent_task):
    """Test that specialist child task has correct properties."""
    await store.save_codex_task(parent_task)

    child = await orchestrator.request_specialist(
        parent_task=parent_task,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review auth code for vulnerabilities",
        why="Handling credentials",
    )

    assert child.parent_task_id == parent_task.id
    assert child.session_id == parent_task.session_id
    assert child.project_id == parent_task.project_id
    assert child.issue_id == parent_task.issue_id
    assert child.workspace_path == parent_task.workspace_path
    assert child.executor == "claude"
    assert "[Specialist]" in child.title
