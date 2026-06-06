"""Conductor loop injects candidate model prices + emits steering events (PR3).

Builds on the PR2 injection test: drives run_issue_conductor_loop with a stub
LLM that captures messages and an event bus that captures emitted events, then
asserts the COST / BUDGET block carries sorted candidate prices and that a
budget_warning / budget_exceeded event fires (or does not) per spend level.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.models import (
    CodexIssue,
    RuntimeCatalog,
    RuntimeExecutorConfig,
    RuntimeModelConfig,
    RuntimeProviderConfig,
    WorkflowGraph,
)


class _Bus:
    def __init__(self):
        self.events: list[dict] = []

    async def append(self, payload):
        self.events.append(payload)


def _catalog() -> RuntimeCatalog:
    return RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="claude", label="Claude",
                providers=[RuntimeProviderConfig(
                    id="anthropic", label="Anthropic",
                    models=[
                        RuntimeModelConfig(id="opus", label="Opus",
                                           input_usd_per_m=15.0, output_usd_per_m=75.0),
                        RuntimeModelConfig(id="haiku", label="Haiku",
                                           input_usd_per_m=0.80, output_usd_per_m=4.0),
                    ],
                )],
            )
        ]
    )


def _make_issue(budget_usd):
    return CodexIssue(
        id=str(uuid4()), session_id="sess-001", project_id="proj-001",
        title="Add feature", description="desc", status="open",
        budget_usd=budget_usd, created_at=datetime.now(), updated_at=datetime.now(),
    )


def _make_graph(issue_id):
    return WorkflowGraph(
        id=str(uuid4()), issue_id=issue_id, dag_json="{}", status="running",
        created_at=datetime.now(), updated_at=datetime.now(), nodes=[], edges=[],
    )


def _ep(status, cost):
    from app.domain.models import ExecutionProcess
    now = datetime.now()
    return ExecutionProcess(
        id=str(uuid4()), task_id="task-1", session_id="sess-001",
        status=status, total_cost_usd=cost, created_at=now, updated_at=now,
    )


def _make_store(issue, graph, *, spend_rows):
    store = MagicMock()
    store.load_codex_issue = AsyncMock(return_value=issue)
    store.load_workflow_graph_for_issue = AsyncMock(return_value=graph)
    store.load_workflow_graph = AsyncMock(return_value=graph)
    store.save_conductor_task = AsyncMock()
    store.save_conductor_turn = AsyncMock()
    store.list_agents = AsyncMock(return_value=[])
    store.load_runtime_catalog = AsyncMock(return_value=None)
    store.save_runtime_catalog = AsyncMock()
    store.list_codex_tasks = AsyncMock(return_value=[{"id": "task-1"}])
    store.list_execution_processes = AsyncMock(return_value=spend_rows)
    return store


async def _run(issue, store, bus):
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    captured = {}

    async def stub_llm(messages=None, tools=None, *args, **kwargs):
        if messages is None and args:
            messages = args[0]
        captured["messages"] = messages
        return {
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "toolu_final",
                         "name": "finalize_task",
                         "input": {"status": "done", "answer": "done"}}],
        }

    async def finalize_tool(inp):
        return {"status": "done", "answer": str(inp.get("answer", ""))}

    registry = MagicMock()
    registry.tools = {"finalize_task": finalize_tool}
    registry.definitions = []

    mock_conductor = MagicMock()
    mock_conductor.get_or_create_state = AsyncMock(return_value=None)
    mock_conductor.append_hot_event = AsyncMock()

    with patch("app.application.conductor_main_loop.build_conductor_tools", return_value=registry), \
         patch("app.application.conductor_main_loop.RuntimeCatalogService") as mock_cs, \
         patch("app.application.conductor_main_loop.call_conductor_llm", side_effect=stub_llm), \
         patch("app.application.conductor_main_loop.resolve_conductor_llm_context", return_value=MagicMock()), \
         patch("app.application.conductor_main_loop.ProjectConductor", return_value=mock_conductor), \
         patch("app.application.conductor_main_loop.record_project_memory", new_callable=AsyncMock):
        mock_cs.return_value.load_catalog = AsyncMock(return_value=_catalog())
        result = await run_issue_conductor_loop(
            issue=issue, project_id="proj-001", store=store,
            event_bus=bus, task_dispatcher_fn=None,
        )
    return result, captured.get("messages")


@pytest.mark.asyncio
async def test_loop_injects_sorted_candidate_prices_when_healthy():
    issue = _make_issue(budget_usd=100.0)
    store = _make_store(issue, _make_graph(issue.id), spend_rows=[_ep("Completed", 1.0)])
    bus = _Bus()
    result, messages = await _run(issue, store, bus)

    assert result.status == "done"
    text = str(messages[0]["content"])
    assert "COST / BUDGET" in text
    assert "Candidate models" in text
    assert text.index("haiku") < text.index("opus")  # cheap before expensive
    assert "Budget is healthy" in text
    # No steering event on the healthy path.
    assert not [e for e in bus.events if e.get("type") in ("budget_warning", "budget_exceeded")]


@pytest.mark.asyncio
async def test_loop_soft_warn_injects_warning_and_emits_event():
    issue = _make_issue(budget_usd=10.0)
    # 8.5 spent / 10 = 85% >= 80% soft-warn.
    store = _make_store(issue, _make_graph(issue.id), spend_rows=[_ep("Completed", 8.5)])
    bus = _Bus()
    result, messages = await _run(issue, store, bus)

    assert result.status == "done"
    text = str(messages[0]["content"])
    assert "BUDGET WARNING" in text
    warnings = [e for e in bus.events if e.get("type") == "budget_warning"]
    assert len(warnings) == 1
    assert warnings[0]["spent_usd"] == 8.5


@pytest.mark.asyncio
async def test_loop_over_budget_injects_wind_down_and_emits_event_without_hard_kill():
    issue = _make_issue(budget_usd=5.0)
    store = _make_store(issue, _make_graph(issue.id), spend_rows=[_ep("Completed", 7.0)])
    bus = _Bus()
    result, messages = await _run(issue, store, bus)

    # Loop is NOT hard-killed: it still completes normally (soft semantics).
    assert result.status == "done"
    text = str(messages[0]["content"])
    assert "OVER BUDGET" in text
    assert "WIND DOWN" in text
    exceeded = [e for e in bus.events if e.get("type") == "budget_exceeded"]
    assert len(exceeded) == 1


@pytest.mark.asyncio
async def test_loop_unlimited_budget_no_steering_event():
    issue = _make_issue(budget_usd=0.0)  # unlimited
    store = _make_store(issue, _make_graph(issue.id), spend_rows=[_ep("Completed", 50.0)])
    bus = _Bus()
    result, messages = await _run(issue, store, bus)

    assert result.status == "done"
    text = str(messages[0]["content"])
    # Isolate the rendered COST / BUDGET block from the static prompt guidelines
    # (the guideline text references "BUDGET WARNING"/"OVER BUDGET" by design).
    block = text.split("## COST / BUDGET", 1)[1].split("## Your Job", 1)[0]
    assert "unlimited" in block
    assert "BUDGET WARNING" not in block
    assert "OVER BUDGET" not in block
    assert not [e for e in bus.events if e.get("type") in ("budget_warning", "budget_exceeded")]
