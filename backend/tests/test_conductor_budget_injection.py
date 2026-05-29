"""Conductor loop injects the budget summary into the LLM request (PR2).

PR2 is visibility-only: the loop must surface accrued spend / budget /
remaining to the orchestrating brain, without changing decision behaviour.
This test drives run_issue_conductor_loop with a stub LLM that captures the
messages it receives and asserts the COST / BUDGET block is present.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.models import CodexIssue, WorkflowGraph


def _make_issue(budget_usd: float | None) -> CodexIssue:
    return CodexIssue(
        id=str(uuid4()),
        session_id="sess-001",
        project_id="proj-001",
        title="Add feature",
        description="desc",
        status="open",
        budget_usd=budget_usd,
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


def _make_store(issue: CodexIssue, graph: WorkflowGraph, *, spend_rows) -> MagicMock:
    store = MagicMock()
    store.load_codex_issue = AsyncMock(return_value=issue)
    store.load_workflow_graph_for_issue = AsyncMock(return_value=graph)
    store.load_workflow_graph = AsyncMock(return_value=graph)
    store.save_conductor_task = AsyncMock()
    store.save_conductor_turn = AsyncMock()
    store.list_agents = AsyncMock(return_value=[])
    store.load_runtime_catalog = AsyncMock(return_value=None)
    store.save_runtime_catalog = AsyncMock()
    # Budget aggregation chain: one task with the supplied execution processes.
    store.list_codex_tasks = AsyncMock(return_value=[{"id": "task-1"}])
    store.list_execution_processes = AsyncMock(return_value=spend_rows)
    return store


def _ep(status: str, cost: float | None):
    from app.domain.models import ExecutionProcess

    now = datetime.now()
    return ExecutionProcess(
        id=str(uuid4()), task_id="task-1", session_id="sess-001",
        status=status, total_cost_usd=cost, created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_loop_injects_budget_summary_into_llm_request():
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue(budget_usd=10.0)
    graph = _make_graph(issue.id)
    # 2.0 completed + 99.0 running (excluded) => spent 2.0 of 10.0.
    spend_rows = [_ep("Completed", 1.5), _ep("Completed", 0.5), _ep("Running", 99.0)]
    store = _make_store(issue, graph, spend_rows=spend_rows)

    captured = {}

    async def stub_llm(messages=None, tools=None, *args, **kwargs):
        if messages is None and args:
            messages = args[0]
        captured["messages"] = messages
        return {
            "stop_reason": "tool_use",
            "content": [{
                "type": "tool_use",
                "id": "toolu_final",
                "name": "finalize_task",
                "input": {"status": "done", "answer": "done"},
            }],
        }

    async def finalize_tool(inp):
        return {"status": str(inp.get("status", "done")), "answer": str(inp.get("answer", ""))}

    registry = MagicMock()
    registry.tools = {"finalize_task": finalize_tool}
    registry.definitions = []

    mock_conductor = MagicMock()
    mock_conductor._load_state = AsyncMock(return_value=None)
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
            project_id="proj-001",
            store=store,
            event_bus=None,
            task_dispatcher_fn=None,
        )

    assert result.status == "done"
    messages = captured.get("messages")
    assert messages, "stub LLM never received messages"
    system_text = str(messages[0]["content"])
    assert "COST / BUDGET" in system_text
    assert "$2.0000" in system_text   # accrued spend (only completed runs)
    assert "$10.0000" in system_text  # resolved budget
    assert "$8.0000" in system_text   # remaining


@pytest.mark.asyncio
async def test_loop_budget_injection_failure_is_non_fatal():
    """If aggregation raises, the loop still runs (visibility is best-effort)."""
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    issue = _make_issue(budget_usd=None)
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph, spend_rows=[])
    store.list_codex_tasks = AsyncMock(side_effect=RuntimeError("db down"))

    captured = {}

    async def stub_llm(messages=None, tools=None, *args, **kwargs):
        if messages is None and args:
            messages = args[0]
        captured["messages"] = messages
        return {
            "stop_reason": "tool_use",
            "content": [{
                "type": "tool_use", "id": "toolu_final",
                "name": "finalize_task", "input": {"status": "done", "answer": "ok"},
            }],
        }

    async def finalize_tool(inp):
        return {"status": "done", "answer": str(inp.get("answer", ""))}

    registry = MagicMock()
    registry.tools = {"finalize_task": finalize_tool}
    registry.definitions = []

    mock_conductor = MagicMock()
    mock_conductor._load_state = AsyncMock(return_value=None)
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
            project_id="proj-001",
            store=store,
            event_bus=None,
            task_dispatcher_fn=None,
        )

    assert result.status == "done"
    # Loop proceeded; the injected budget block was simply omitted from the
    # prompt. (The static prompt guidelines reference the "## COST / BUDGET"
    # header by name, so we assert on the block BODY, which only the injected
    # render emits, rather than the header substring.)
    content = str(captured["messages"][0]["content"])
    assert "Spent so far:" not in content
