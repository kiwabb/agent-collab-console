"""Phase 1 tests — parallel engineer fan-out template + orchestrator
heuristic that prefers it when an issue spans frontend + backend.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.application.workflow_orchestrator import (
    WorkflowOrchestrator,
    _spans_frontend_and_backend,
)
from app.application.workflow_templates import (
    get_template,
    template_to_dag,
)
from app.domain.models import Agent, CodexIssue


def _agent(role_key: str) -> Agent:
    return Agent(
        id=f"agent-{role_key}",
        name=role_key,
        role_key=role_key,
        system_prompt_template="",
    )


def _all_agents() -> list[Agent]:
    return [
        _agent("product_manager"),
        _agent("architect"),
        _agent("engineer"),
        _agent("engineer_frontend"),
        _agent("engineer_backend"),
        _agent("qa"),
    ]


def test_feature_parallel_template_materializes_y_shape():
    template = get_template("feature_parallel")
    assert template is not None
    dag = template_to_dag(template, _all_agents())
    assert dag is not None

    node_keys = {n["node_key"] for n in dag["nodes"]}
    assert node_keys == {
        "product_manager",
        "architect",
        "engineer_frontend",
        "engineer_backend",
        "qa",
    }

    # Architect should have 2 outgoing fan-out edges, QA should have 2
    # incoming fan-out edges, and there should be no default sequence
    # edges between FE/BE (they run in parallel).
    by_pair = {(e["from_node_key"], e["to_node_key"]): e for e in dag["edges"]}
    assert ("product_manager", "architect") in by_pair
    assert ("architect", "engineer_frontend") in by_pair
    assert ("architect", "engineer_backend") in by_pair
    assert ("engineer_frontend", "qa") in by_pair
    assert ("engineer_backend", "qa") in by_pair
    # No accidental sequence FE → BE
    assert ("engineer_frontend", "engineer_backend") not in by_pair
    # Fan-out edges are typed correctly
    assert by_pair[("architect", "engineer_frontend")]["edge_type"] == "parallel-fanout"
    assert by_pair[("engineer_backend", "qa")]["edge_type"] == "parallel-fanout"
    # PM → Architect is still a plain sequence
    assert by_pair[("product_manager", "architect")]["edge_type"] == "sequence"


def test_spans_frontend_and_backend_detects_mixed_issue():
    issue = CodexIssue(
        id="i1",
        session_id="s1",
        title="实现登录页面 + API",
        description="新增登录页(frontend 组件)并实现 /api/login 端点(backend)",
        current_phase="requirements",
        status="open",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assert _spans_frontend_and_backend(issue) is True


def test_spans_frontend_and_backend_skips_backend_only():
    issue = CodexIssue(
        id="i2",
        session_id="s1",
        title="add /api/echo endpoint",
        description="Server-side only — no client work",
        current_phase="requirements",
        status="open",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assert _spans_frontend_and_backend(issue) is False


@pytest.mark.asyncio
async def test_heuristic_propose_picks_fanout_when_issue_spans_both():
    issue = CodexIssue(
        id="i3",
        session_id="s1",
        title="登录功能",
        description="frontend 实现登录页 + backend 实现 /api/login API endpoint",
        current_phase="requirements",
        status="open",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    orch = WorkflowOrchestrator()
    dag = await orch.propose_graph(issue, _all_agents(), use_llm=False)

    node_keys = {n["node_key"] for n in dag["nodes"]}
    assert "engineer_frontend" in node_keys
    assert "engineer_backend" in node_keys
    # The plain `engineer` shouldn't be in the fan-out DAG
    assert "engineer" not in node_keys

    fanout_edges = [
        e for e in dag["edges"] if e["edge_type"] == "parallel-fanout"
    ]
    # 4 fan-out edges: Arch→FE, Arch→BE, FE→QA, BE→QA
    assert len(fanout_edges) == 4


@pytest.mark.asyncio
async def test_heuristic_propose_falls_back_to_chain_when_backend_only():
    issue = CodexIssue(
        id="i4",
        session_id="s1",
        title="add health-check endpoint",
        description="Server-side route returning 200 with a JSON status payload",
        current_phase="requirements",
        status="open",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    orch = WorkflowOrchestrator()
    dag = await orch.propose_graph(issue, _all_agents(), use_llm=False)
    node_keys = [n["node_key"] for n in dag["nodes"]]
    # Default single-chain feature template
    assert node_keys == ["product_manager", "architect", "engineer", "qa"]
    assert all(e["edge_type"] == "sequence" for e in dag["edges"])
