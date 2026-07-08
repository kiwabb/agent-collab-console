from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.agent_seed import seed_builtin_agents
from app.application.four_phase_preset import (
    backfill_graphs_for_existing_issues,
    ensure_four_phase_preset,
)
from app.domain.models import CodexIssue


def test_four_phase_preset_backfills_existing_issues_idempotently(tmp_path: Path):
    async def run() -> None:
        store = AsyncSQLiteStore(tmp_path / "four-phase.db")
        try:
            await seed_builtin_agents(store)
            await ensure_four_phase_preset(store)
            await ensure_four_phase_preset(store)

            issue = CodexIssue(
                id="issue-four-phase",
                session_id="session-four-phase",
                title="Ship the release",
                description="Existing issue without a workflow graph",
            )
            await store.save_codex_issue(issue)

            assert await backfill_graphs_for_existing_issues(store) == 1
            assert await backfill_graphs_for_existing_issues(store) == 0

            graph = await store.load_workflow_graph_for_issue(issue.id)
            assert graph is not None
            assert graph.created_by == "migration"
            assert graph.status == "draft"
            assert [node.node_key for node in graph.nodes] == [
                "product_manager",
                "architect",
                "engineer",
                "qa",
            ]
            assert [edge.from_node_key for edge in graph.edges] == [
                "product_manager",
                "architect",
                "engineer",
            ]
            assert [edge.to_node_key for edge in graph.edges] == [
                "architect",
                "engineer",
                "qa",
            ]
            dag = json.loads(graph.dag_json)
            assert dag["meta"]["created_by"] == "migration"

            conn = await store._get_conn()
            async with conn.execute("SELECT COUNT(*) FROM workflow_presets WHERE name = 'four_phase'") as cur:
                row = await cur.fetchone()
                assert row is not None
                preset_count = row[0]
            assert preset_count == 1
        finally:
            await store.close()

    asyncio.run(run())
