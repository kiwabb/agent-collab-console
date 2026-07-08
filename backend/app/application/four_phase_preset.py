"""Materialize the legacy 4-phase pipeline as a WorkflowGraph for issues that
don't yet have one. Used by the startup migration so that opening an old
issue under the new DAG-aware UI never errors out.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable
from datetime import datetime
from typing import Protocol
from uuid import uuid4

import aiosqlite

from app.domain.models import Agent, WorkflowEdge, WorkflowGraph, WorkflowNode

logger = logging.getLogger(__name__)

_FOUR_PHASE_ORDER = ["product_manager", "architect", "engineer", "qa"]


class FourPhasePresetStore(Protocol):
    def _get_conn(self) -> Awaitable[aiosqlite.Connection]: ...

    def list_agents(self, *, workspace_id: str | None = None) -> Awaitable[list[Agent]]: ...

    def save_workflow_graph(
        self,
        graph: WorkflowGraph,
        *,
        nodes: list[WorkflowNode] | None = None,
        edges: list[WorkflowEdge] | None = None,
    ) -> Awaitable[None]: ...


async def ensure_four_phase_preset(store: FourPhasePresetStore | None) -> None:
    """Register a re-usable 'four_phase' preset row (idempotent)."""
    if store is None:
        return
    # We persist a preset record via direct SQL since there's no dedicated helper.
    # The dag_template_json holds role_keys only — agent_ids are resolved at graph creation time.
    conn = await store._get_conn()
    template = {
        "nodes": [{"node_key": rk, "role_key": rk, "title": rk} for rk in _FOUR_PHASE_ORDER],
        "edges": [
            {"from_node_key": a, "to_node_key": b, "edge_type": "sequence"}
            for a, b in zip(_FOUR_PHASE_ORDER, _FOUR_PHASE_ORDER[1:])  # noqa: B905, RUF007
        ],
    }
    await conn.execute(
        """INSERT OR IGNORE INTO workflow_presets (id, name, description, dag_template_json, is_builtin, created_at)
           VALUES (?, 'four_phase', 'Legacy PM→Architect→Engineer→QA pipeline', ?, 1, ?)""",
        (str(uuid4()), json.dumps(template), datetime.now().isoformat()),
    )
    await conn.commit()


async def backfill_graphs_for_existing_issues(store: FourPhasePresetStore | None) -> int:
    """Create a 4-phase graph for any issue that doesn't have one yet.

    Idempotent: if an issue already has a graph row, it's left alone.
    Returns the number of graphs created. Uses agent_ids from the live registry
    so newly seeded agents become eligible immediately.
    """
    if store is None:
        return 0
    agents = await store.list_agents(workspace_id=None)
    role_to_agent = {a.role_key: a for a in agents}
    if not all(rk in role_to_agent for rk in _FOUR_PHASE_ORDER):
        logger.warning(
            "Skipping graph backfill — built-in agents missing %s",
            [rk for rk in _FOUR_PHASE_ORDER if rk not in role_to_agent],
        )
        return 0
    # Pull every issue id; filter those without a graph.
    conn = await store._get_conn()
    conn.row_factory = aiosqlite.Row
    async with conn.execute("SELECT id FROM codex_issues") as cur:
        issue_rows = await cur.fetchall()
    async with conn.execute("SELECT issue_id FROM workflow_graphs") as cur:
        graph_rows = await cur.fetchall()
    have_graph = {r["issue_id"] for r in graph_rows}
    created = 0
    for r in issue_rows:
        issue_id = r["id"]
        if issue_id in have_graph:
            continue
        await _create_four_phase_graph(store, issue_id, role_to_agent)
        created += 1
    return created


async def _create_four_phase_graph(
    store: FourPhasePresetStore, issue_id: str, role_to_agent: dict[str, Agent]
) -> WorkflowGraph:
    graph_id = str(uuid4())
    now = datetime.now()
    nodes: list[WorkflowNode] = []
    for role_key in _FOUR_PHASE_ORDER:
        agent = role_to_agent[role_key]
        nodes.append(
            WorkflowNode(
                id=str(uuid4()),
                graph_id=graph_id,
                node_key=role_key,
                agent_id=agent.id,
                title=agent.name,
                status="pending",
                artifact_dir=agent.artifact_subdir,
                created_at=now,
            )
        )
    edges: list[WorkflowEdge] = []
    for prev, curr in zip(_FOUR_PHASE_ORDER, _FOUR_PHASE_ORDER[1:]):  # noqa: B905, RUF007
        edges.append(
            WorkflowEdge(
                id=str(uuid4()),
                graph_id=graph_id,
                from_node_key=prev,
                to_node_key=curr,
                edge_type="sequence",
                created_at=now,
            )
        )
    dag = {
        "meta": {
            "intent": "feature",
            "rationale": "Auto-migrated legacy 4-phase issue.",
            "created_by": "migration",
        },
        "nodes": [
            {
                "node_key": n.node_key,
                "agent_id": n.agent_id,
                "role_key": n.node_key,
                "title": n.title,
            }
            for n in nodes
        ],
        "edges": [
            {
                "from_node_key": e.from_node_key,
                "to_node_key": e.to_node_key,
                "edge_type": e.edge_type,
            }
            for e in edges
        ],
    }
    graph = WorkflowGraph(
        id=graph_id,
        issue_id=issue_id,
        preset_id=None,
        status="draft",
        dag_json=json.dumps(dag, ensure_ascii=False),
        created_by="migration",
        created_at=now,
        updated_at=now,
        nodes=nodes,
        edges=edges,
    )
    await store.save_workflow_graph(graph, nodes=nodes, edges=edges)
    return graph
