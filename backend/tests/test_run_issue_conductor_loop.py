"""Tests for run_issue_conductor_loop in conductor_main_loop.py."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.application.conductor_policy import ConductorPolicyDecision
from app.domain.models import CodexIssue, ProjectConductorState, WorkflowGraph


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


def test_build_issue_conductor_prompt_includes_source_informed_operating_contract():
    from app.application.conductor_main_loop import build_issue_conductor_prompt

    issue = _make_issue()

    prompt = build_issue_conductor_prompt(
        issue=issue,
        project_context="",
        budget_context="",
        language_directive="",
    )

    assert "## Operating Contract" in prompt
    assert "Decision loop" in prompt
    assert "Delegation prompt quality bar" in prompt
    assert "Use `dispatch_batch` only for independent work" in prompt
    assert "Never treat `artifact_invalid` as success" in prompt
    assert "Users may inject `[USER INTERJECTION]` messages" in prompt


def test_build_issue_conductor_prompt_includes_project_memory_context():
    from app.application.conductor_main_loop import build_issue_conductor_prompt

    issue = _make_issue()

    prompt = build_issue_conductor_prompt(
        issue=issue,
        project_context=(
            "\n\n## PROJECT CONTEXT (team_notes)\nPinned: preserve API contracts."
            "\n\n## RECENT PROJECT HISTORY\n{'summary': 'QA caught stale conductor memory.'}"
        ),
        budget_context="",
        language_directive="",
    )

    assert "Pinned: preserve API contracts." in prompt
    assert "QA caught stale conductor memory." in prompt


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
    event_bus = MagicMock()
    event_bus.append = AsyncMock()

    registry = _make_noop_conductor_tools_registry()

    mock_conductor = MagicMock()
    mock_conductor.get_or_create_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=None), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=None)

        result = await run_issue_conductor_loop(
            issue=issue,
            project_id="proj-001",
            store=store,
            event_bus=event_bus,
            task_dispatcher_fn=None,
        )

    assert result.status == "done"
    # ConductorTask is saved on start, phase transitions, and finalization.
    assert store.save_conductor_task.call_count >= 2
    final_task = store.save_conductor_task.call_args_list[-1][0][0]
    assert final_task.status == "done"
    status_events = [call.args[0] for call in event_bus.append.call_args_list if call.args and call.args[0].get("type") == "conductor_status"]
    assert status_events[0]["phase"] == "awaiting_llm"
    assert status_events[-1]["phase"] == "done"


@pytest.mark.asyncio
async def test_loop_records_durable_conductor_lease():
    """A live Conductor loop persists a runner lease so reload recovery can detect orphans."""
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph)
    registry = _make_noop_conductor_tools_registry()

    mock_conductor = MagicMock()
    mock_conductor.get_or_create_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=None), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=None)

        await run_issue_conductor_loop(
            issue=issue,
            project_id="proj-001",
            store=store,
            event_bus=None,
            task_dispatcher_fn=None,
        )

    first_task = store.save_conductor_task.call_args_list[0][0][0]
    saved_tasks = [call.args[0] for call in store.save_conductor_task.call_args_list]
    assert first_task.lease_owner
    assert first_task.heartbeat_at is not None
    assert any(task.heartbeat_at is not None for task in saved_tasks)


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
    mock_conductor.get_or_create_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_conductor_llm", side_effect=make_stub_llm()), \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=MagicMock()), \
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
async def test_loop_injects_project_conductor_memory_into_llm_prompt():
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph)

    captured = {}

    async def stub_llm(messages=None, tools=None, *args, **kwargs):
        if messages is None and args:
            messages = args[0]
        captured["messages"] = messages
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "memory injected"},
                }
            ],
        }

    async def finalize_tool(inp):
        return {"status": str(inp.get("status", "done")), "answer": str(inp.get("answer", ""))}

    registry = MagicMock()
    registry.tools = {"finalize_task": finalize_tool}
    registry.definitions = []

    mock_conductor = MagicMock()
    mock_conductor.get_or_create_state = AsyncMock(
        return_value=ProjectConductorState(
            project_id=issue.project_id,
            pinned_text="Pinned: keep conductor decisions source-informed.",
            warm_summaries_json=json.dumps([
                {"summary": "Recent run: parallel agents conflicted without clear prompts."}
            ]),
        )
    )
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_conductor_llm", side_effect=stub_llm), \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=MagicMock()), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=MagicMock())

        result = await run_issue_conductor_loop(
            issue=issue,
            project_id=issue.project_id,
            store=store,
            event_bus=None,
            task_dispatcher_fn=None,
        )

    assert result.status == "done"
    mock_conductor.get_or_create_state.assert_awaited_once()
    prompt = str(captured["messages"][0]["content"])
    assert "Pinned: keep conductor decisions source-informed." in prompt
    assert "parallel agents conflicted without clear prompts" in prompt


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
    mock_conductor.get_or_create_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_conductor_llm", side_effect=RuntimeError("boom")), \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=MagicMock()), \
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
    mock_conductor.get_or_create_state = AsyncMock(return_value=None)
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
         patch("app.application.conductor_main_loop.call_conductor_llm", side_effect=fake_llm), \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=MagicMock()), \
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


@pytest.mark.asyncio
async def test_loop_records_policy_decision_and_injects_prompt_hint():
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph)
    store.save_conductor_turn = AsyncMock()
    store.list_conductor_turns = AsyncMock(return_value=[])
    event_bus = MagicMock()
    event_bus.append = AsyncMock()

    captured = {}

    async def stub_llm(messages=None, tools=None, *args, **kwargs):
        if messages is None and args:
            messages = args[0]
        captured["prompt"] = str(messages[0]["content"])
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "policy hint observed"},
                }
            ],
        }

    registry = _make_noop_conductor_tools_registry()
    mock_conductor = MagicMock()
    mock_conductor._load_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()
    policy = ConductorPolicyDecision(
        action="call_llm",
        reason_code="role_retries_exhausted",
        reason="engineer exhausted redispatch budget",
        prompt_hint="Do not dispatch engineer again.",
        evidence=[{"kind": "test"}],
    )

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_conductor_llm", side_effect=stub_llm), \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=MagicMock()), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock), \
         patch("app.application.conductor_main_loop.decide_conductor_policy", return_value=policy):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=MagicMock())

        result = await run_issue_conductor_loop(
            issue=issue,
            project_id="proj-001",
            store=store,
            event_bus=event_bus,
            task_dispatcher_fn=None,
        )

    assert result.status == "done"
    assert "## POLICY HINT" in captured["prompt"]
    assert "Do not dispatch engineer again." in captured["prompt"]
    policy_turns = [
        call.args[0]
        for call in store.save_conductor_turn.call_args_list
        if call.args and call.args[0].kind == "policy_decision"
    ]
    assert len(policy_turns) == 1
    assert "role_retries_exhausted" in policy_turns[0].payload_json
    assert any(
        call.args
        and call.args[0].get("type") == "conductor_turn"
        and call.args[0].get("kind") == "policy_decision"
        for call in event_bus.append.call_args_list
    )


@pytest.mark.asyncio
async def test_loop_safe_skip_avoids_conductor_llm_call():
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph)
    store.save_conductor_turn = AsyncMock()
    store.list_conductor_turns = AsyncMock(return_value=[])
    registry = _make_noop_conductor_tools_registry()
    mock_conductor = MagicMock()
    mock_conductor._load_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()
    policy = ConductorPolicyDecision(
        action="skip_llm",
        reason_code="recent_safe_finalize",
        reason="Recent Conductor evidence already finalized successfully; avoid a redundant LLM turn.",
        evidence=[{"kind": "recent_finalize_count", "count": 2}],
    )

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_conductor_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=MagicMock()), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock), \
         patch("app.application.conductor_main_loop.decide_conductor_policy", return_value=policy):

        mock_cs.return_value.load_catalog = AsyncMock(return_value=MagicMock())

        result = await run_issue_conductor_loop(
            issue=issue,
            project_id="proj-001",
            store=store,
            event_bus=None,
            task_dispatcher_fn=None,
        )

    assert result.status == "done"
    assert result.final_text == policy.reason
    assert mock_llm.await_count == 0
