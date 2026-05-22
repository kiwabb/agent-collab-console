"""Tests for run_issue_conductor_loop in conductor_main_loop.py."""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.models import CodexIssue, WorkflowGraph


def _make_issue() -> CodexIssue:
    return CodexIssue(
        id=str(uuid4()),
        session_id="sess-001",
        project_id="proj-001",
        title="Add new feature",
        description="Feature description",
        status="open",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _make_graph(issue_id: str) -> WorkflowGraph:
    return WorkflowGraph(
        id=str(uuid4()),
        issue_id=issue_id,
        dag_json="{}",
        status="running",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nodes=[],
        edges=[],
    )


def _make_store(issue: CodexIssue, graph: WorkflowGraph) -> MagicMock:
    store = MagicMock()
    store.load_codex_issue = AsyncMock(return_value=issue)
    store.load_workflow_graph_for_issue = AsyncMock(return_value=graph)
    store.load_workflow_graph = AsyncMock(return_value=graph)
    store.save_conductor_task = AsyncMock()
    store.list_agents = AsyncMock(return_value=[])
    store.load_runtime_catalog = AsyncMock(return_value=None)
    store.save_runtime_catalog = AsyncMock()
    return store


def _make_noop_conductor_tools_registry():
    """Build a minimal ConductorToolRegistry for testing."""
    from app.application.conductor_main_loop import ConductorLoopResult

    async def finalize_tool(inp):
        return {"status": str(inp.get("status", "done")), "answer": str(inp.get("answer", ""))}

    registry = MagicMock()
    registry.tools = {"finalize_task": finalize_tool}
    registry.definitions = [
        {
            "name": "finalize_task",
            "description": "Finish",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
    ]
    return registry


@pytest.mark.asyncio
async def test_loop_calls_finalize():
    """test_loop_calls_finalize: stub LLM immediately calls finalize_task; ConductorTask saved with status=done."""
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph)

    registry = _make_noop_conductor_tools_registry()

    mock_conductor = MagicMock()
    mock_conductor._load_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.resolve_streaming_context", return_value=None), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=None)

        result = await run_issue_conductor_loop(
            issue=issue,
            project_id="proj-001",
            store=store,
            event_bus=None,
            task_dispatcher_fn=None,
        )

    assert result.status == "done"
    # ConductorTask was saved twice (running + final)
    assert store.save_conductor_task.call_count == 2
    final_task = store.save_conductor_task.call_args_list[-1][0][0]
    assert final_task.status == "done"


@pytest.mark.asyncio
async def test_loop_dispatches_pm():
    """test_loop_dispatches_pm: stub LLM calls dispatch_subagent role=pm then finalize; verify dispatch_role called."""
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph)

    dispatched_roles: list[str] = []

    async def mock_dispatch_subagent(tool_input):
        """Fake dispatch_subagent that records calls and returns success."""
        role = tool_input.get("role", "")
        dispatched_roles.append(role)
        return {"task_id": str(uuid4()), "role": role, "status": "done", "summary": f"{role} completed"}

    async def finalize_tool(inp):
        return {"status": str(inp.get("status", "done")), "answer": str(inp.get("answer", ""))}

    # Turn-based LLM stub
    llm_turn = 0

    def make_stub_llm():
        async def stub_llm(*args, messages=None, tools=None, **kwargs):
            nonlocal llm_turn
            if messages is None and args:
                messages = args[0]
            llm_turn += 1
            if llm_turn == 1:
                return {
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_pm_001",
                            "name": "dispatch_subagent",
                            "input": {"role": "pm"},
                        }
                    ],
                }
            else:
                return {
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_final_001",
                            "name": "finalize_task",
                            "input": {"status": "done", "answer": "PM dispatched and done"},
                        }
                    ],
                }
        return stub_llm

    registry = MagicMock()
    registry.tools = {
        "dispatch_subagent": mock_dispatch_subagent,
        "finalize_task": finalize_tool,
    }
    registry.definitions = []

    mock_conductor = MagicMock()
    mock_conductor._load_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_llm_with_tools", side_effect=make_stub_llm()), \
         patch("app.application.conductor_main_loop.resolve_streaming_context", return_value=MagicMock()), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=None)

        result = await run_issue_conductor_loop(
            issue=issue,
            project_id="proj-001",
            store=store,
            event_bus=None,
            task_dispatcher_fn=None,
        )

    assert result.status == "done"
    assert "pm" in dispatched_roles


@pytest.mark.asyncio
async def test_loop_marks_failed_and_emits_failure_event():
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph)
    store.save_conductor_turn = AsyncMock()
    event_bus = MagicMock()
    event_bus.append = AsyncMock()

    registry = _make_noop_conductor_tools_registry()
    mock_conductor = MagicMock()
    mock_conductor._load_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_llm_with_tools", side_effect=RuntimeError("boom")), \
         patch("app.application.conductor_main_loop.resolve_streaming_context", return_value=MagicMock()), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=MagicMock())

        result = await run_issue_conductor_loop(
            issue=issue,
            project_id="proj-001",
            store=store,
            event_bus=event_bus,
            task_dispatcher_fn=None,
        )

    assert result.status == "failed"
    final_task = store.save_conductor_task.call_args_list[-1][0][0]
    assert final_task.status == "failed"
    assert "\"status\": \"failed\"" in (final_task.result_json or "")
    assert any(call.args[0]["type"] == "conductor_failed" for call in event_bus.append.call_args_list)


@pytest.mark.asyncio
async def test_loop_pause_resume_cancels_inflight_llm_and_retries():
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.conductor_pause_registry import ConductorPauseRegistry
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None
    ConductorPauseRegistry._instance = None

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph)

    registry = _make_noop_conductor_tools_registry()
    mock_conductor = MagicMock()
    mock_conductor._load_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    first_call_started = asyncio.Event()
    llm_calls = 0

    async def fake_llm(messages=None, tools=None, *args, **kwargs):
        nonlocal llm_calls
        llm_calls += 1
        if llm_calls == 1:
            first_call_started.set()
            await asyncio.sleep(3600)
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "resumed cleanly"},
                }
            ],
        }

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_llm_with_tools", side_effect=fake_llm), \
         patch("app.application.conductor_main_loop.resolve_streaming_context", return_value=MagicMock()), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=MagicMock())
        loop_task = asyncio.create_task(
            run_issue_conductor_loop(
                issue=issue,
                project_id="proj-001",
                store=store,
                event_bus=None,
                task_dispatcher_fn=None,
            )
        )

        await first_call_started.wait()

        while store.save_conductor_task.call_count == 0:
            await asyncio.sleep(0)
        conductor_task = store.save_conductor_task.call_args_list[0][0][0]
        registry_instance = ConductorPauseRegistry.instance()
        assert await registry_instance.request_pause(conductor_task.id) is True

        for _ in range(50):
            if any(call.args[0].status == "paused" for call in store.save_conductor_task.call_args_list):
                break
            await asyncio.sleep(0.01)
        assert any(call.args[0].status == "paused" for call in store.save_conductor_task.call_args_list)

        assert await registry_instance.resume(conductor_task.id) is True
        result = await asyncio.wait_for(loop_task, timeout=3)

    assert result.status == "done"
    assert result.final_text == "resumed cleanly"
    assert llm_calls >= 2
