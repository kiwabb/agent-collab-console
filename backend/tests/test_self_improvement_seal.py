from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.application import conductor_main_loop as cml
from app.domain.models import CodexIssue, WorkflowGraph


class SealStore:
    def __init__(self):
        self.graph = WorkflowGraph(
            id="graph-1",
            issue_id="issue-1",
            preset_id="preset-1",
            status="running",
            dag_json="{}",
            created_at=datetime(2026, 6, 8, 10, 0, 0),
            updated_at=datetime(2026, 6, 8, 10, 0, 0),
        )
        self.saved_issue = None
        self.saved_graph = None

    async def load_workflow_graph_for_issue(self, issue_id):
        return self.graph

    async def save_workflow_graph(self, graph):
        self.saved_graph = graph

    async def save_codex_issue(self, issue):
        self.saved_issue = issue

    async def load_project(self, project_id):
        return None


def _issue():
    return CodexIssue(
        id="issue-1",
        session_id="session-1",
        title="Done issue",
        description="Completed",
        status="open",
        project_id="project-1",
    )


@pytest.mark.asyncio
async def test_done_seal_records_memory_then_self_improvement():
    store = SealStore()
    with (
        patch(
            "app.application.conductor_main_loop.record_project_memory", new=AsyncMock()
        ) as memory,
        patch(
            "app.application.conductor_main_loop.record_issue_self_improvement", new=AsyncMock()
        ) as improve,
    ):
        await cml._seal_graph_and_issue_status(
            store=store, issue=_issue(), event_bus=None, result_status="done"
        )

    memory.assert_awaited_once_with("graph-1", store)
    improve.assert_awaited_once()
    assert improve.await_args is not None
    assert improve.await_args.args[0].id == "issue-1"
    assert improve.await_args.args[1] is store
    assert store.saved_issue is not None
    assert store.saved_issue.status == "completed"


@pytest.mark.asyncio
async def test_self_improvement_failure_does_not_block_terminal_status():
    store = SealStore()
    with (
        patch("app.application.conductor_main_loop.record_project_memory", new=AsyncMock()),
        patch(
            "app.application.conductor_main_loop.record_issue_self_improvement",
            new=AsyncMock(side_effect=RuntimeError("proposal store down")),
        ),
    ):
        await cml._seal_graph_and_issue_status(
            store=store, issue=_issue(), event_bus=None, result_status="done"
        )

    assert store.saved_graph is not None
    assert store.saved_issue is not None
    assert store.saved_graph.status == "done"
    assert store.saved_issue.status == "completed"
