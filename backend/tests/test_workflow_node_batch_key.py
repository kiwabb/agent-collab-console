"""Round-trip tests for WorkflowNode.batch_key persistence.

batch_key groups nodes that were fanned out together via dispatch_batch so the
WorkflowGraph / mesh UI can render them as a single parallel swimlane. It must
survive a save_workflow_graph / add_workflow_node → load_workflow_graph_for_issue
round-trip through the SQLite store, and default to None for legacy/serial nodes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.domain.models import WorkflowGraph, WorkflowNode


def _graph(issue_id: str) -> WorkflowGraph:
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


def _node(graph_id: str, node_key: str, batch_key: str | None) -> WorkflowNode:
    return WorkflowNode(
        id=str(uuid4()),
        graph_id=graph_id,
        node_key=node_key,
        agent_id="agent-engineer",
        title=node_key.title(),
        status="running",
        task_id=f"task-{node_key}",
        batch_key=batch_key,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def test_batch_key_round_trips_via_add_workflow_node(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "batch-add.db")
        issue_id = str(uuid4())
        graph = _graph(issue_id)
        await store.save_workflow_graph(graph, nodes=[], edges=[])

        bk = "batch-deadbeef"
        await store.add_workflow_node(_node(graph.id, "engineer", bk))
        await store.add_workflow_node(_node(graph.id, "qa", bk))
        await store.add_workflow_node(_node(graph.id, "architect", None))

        loaded = await store.load_workflow_graph_for_issue(issue_id)
        await store.close()

        assert loaded is not None
        by_key = {n.node_key: n for n in loaded.nodes}
        # Same-batch nodes share the persisted batch_key.
        assert by_key["engineer"].batch_key == bk
        assert by_key["qa"].batch_key == bk
        # Serial node stays ungrouped.
        assert by_key["architect"].batch_key is None

    asyncio.run(run())


def test_batch_key_round_trips_via_save_workflow_graph(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "batch-save.db")
        issue_id = str(uuid4())
        graph = _graph(issue_id)
        bk = "batch-cafe0001"
        nodes = [
            _node(graph.id, "engineer", bk),
            _node(graph.id, "qa", bk),
            _node(graph.id, "pm", None),
        ]
        await store.save_workflow_graph(graph, nodes=nodes, edges=[])

        loaded = await store.load_workflow_graph_for_issue(issue_id)
        await store.close()

        assert loaded is not None
        by_key = {n.node_key: n for n in loaded.nodes}
        assert by_key["engineer"].batch_key == bk
        assert by_key["qa"].batch_key == bk
        assert by_key["pm"].batch_key is None

    asyncio.run(run())
