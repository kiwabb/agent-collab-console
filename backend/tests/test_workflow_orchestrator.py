"""PR2: WorkflowOrchestrator heuristic + /plan endpoint."""
from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from app.application.agent_seed import seed_builtin_agents
from app.application.workflow_orchestrator import WorkflowOrchestrator, validate_dag
from app.domain.models import CodexIssue


def _run(coro):
    import asyncio as a
    loop = a.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def reseed_builtins():
    import app.bootstrap as bootstrap_module
    if bootstrap_module.async_store is not None:
        _run(seed_builtin_agents(bootstrap_module.async_store))
    yield


def _make_issue(title: str, description: str = "") -> CodexIssue:
    return CodexIssue(
        id=str(uuid4()),
        session_id="ws-test",
        title=title,
        description=description,
        created_at=datetime.now(),
    )


def test_feature_proposes_full_four_phase():
    import app.bootstrap as bootstrap_module
    orchestrator = WorkflowOrchestrator(store=bootstrap_module.async_store)
    dag = _run(orchestrator.propose_graph(_make_issue("Implement new export-to-csv feature")))
    role_keys = [n["role_key"] for n in dag["nodes"]]
    assert role_keys == ["product_manager", "architect", "engineer", "qa"]
    assert dag["meta"]["intent"] == "feature"
    # All edges are sequence and form a chain.
    edges = dag["edges"]
    assert all(e["edge_type"] == "sequence" for e in edges)
    chain = [(e["from_node_key"], e["to_node_key"]) for e in edges]
    assert chain == [
        ("product_manager", "architect"),
        ("architect", "engineer"),
        ("engineer", "qa"),
    ]


def test_docs_only_skips_arch_and_qa():
    import app.bootstrap as bootstrap_module
    orchestrator = WorkflowOrchestrator(store=bootstrap_module.async_store)
    dag = _run(orchestrator.propose_graph(_make_issue("Fix typo in README")))
    role_keys = [n["role_key"] for n in dag["nodes"]]
    assert role_keys == ["product_manager", "engineer"]
    assert dag["meta"]["intent"] == "docs_only"


def test_bug_keeps_pm_engineer_qa_but_skips_arch():
    import app.bootstrap as bootstrap_module
    orchestrator = WorkflowOrchestrator(store=bootstrap_module.async_store)
    dag = _run(orchestrator.propose_graph(
        _make_issue("Fix login crash on Safari", "User reports auth fails intermittently")
    ))
    role_keys = [n["role_key"] for n in dag["nodes"]]
    assert role_keys == ["product_manager", "engineer", "qa"]
    assert dag["meta"]["intent"] == "bug"


def test_hotfix_skips_pm_and_arch():
    import app.bootstrap as bootstrap_module
    orchestrator = WorkflowOrchestrator(store=bootstrap_module.async_store)
    dag = _run(orchestrator.propose_graph(_make_issue("Hotfix: payment webhook timing out")))
    role_keys = [n["role_key"] for n in dag["nodes"]]
    assert role_keys == ["engineer", "qa"]


def test_refactor_skips_pm_and_qa():
    import app.bootstrap as bootstrap_module
    orchestrator = WorkflowOrchestrator(store=bootstrap_module.async_store)
    dag = _run(orchestrator.propose_graph(_make_issue("Refactor user service module")))
    role_keys = [n["role_key"] for n in dag["nodes"]]
    assert role_keys == ["architect", "engineer"]


def test_validate_dag_rejects_unknown_agent_id():
    bad = {
        "meta": {},
        "nodes": [{"node_key": "n1", "agent_id": "doesnotexist", "role_key": "x"}],
        "edges": [],
    }
    with pytest.raises(ValueError):
        validate_dag(bad, agent_ids={"some-real-id"})


def test_validate_dag_rejects_cycle():
    bad = {
        "meta": {},
        "nodes": [
            {"node_key": "a", "agent_id": "x", "role_key": "r"},
            {"node_key": "b", "agent_id": "x", "role_key": "r"},
        ],
        "edges": [
            {"from_node_key": "a", "to_node_key": "b", "edge_type": "sequence"},
            {"from_node_key": "b", "to_node_key": "a", "edge_type": "sequence"},
        ],
    }
    with pytest.raises(ValueError, match="cycle"):
        validate_dag(bad, agent_ids={"x"})


def test_validate_dag_allows_refine_loop_back_edge():
    ok = {
        "meta": {},
        "nodes": [
            {"node_key": "a", "agent_id": "x", "role_key": "r"},
            {"node_key": "b", "agent_id": "x", "role_key": "r"},
        ],
        "edges": [
            {"from_node_key": "a", "to_node_key": "b", "edge_type": "sequence"},
            {"from_node_key": "b", "to_node_key": "a", "edge_type": "refine-loop"},
        ],
    }
    validate_dag(ok, agent_ids={"x"})  # no exception


def test_plan_endpoint_returns_dag(client):
    # Create an issue then call /plan
    ws = client.post("/api/codex/workspaces", json={
        "title": "W", "project_id": "_test_no_project_",
    })
    # Workspaces likely require a real project; fall back to creating a session-only issue.
    if ws.status_code >= 400:
        # Use the direct codex session path (no git project required).
        import app.bootstrap as bootstrap_module
        from app.domain.models import CodexSession
        session = CodexSession(id=str(uuid4()), title="W", cwd="/tmp", status="idle",
                               created_at=datetime.now())
        _run(bootstrap_module.async_store.save_codex_session(session))
        issue = CodexIssue(id=str(uuid4()), session_id=session.id, title="Add login page",
                           description="New feature", created_at=datetime.now())
        _run(bootstrap_module.async_store.save_codex_issue(issue))
        issue_id = issue.id
    else:
        ws_id = ws.json()["id"]
        issue_resp = client.post("/api/codex/issues", json={
            "session_id": ws_id, "title": "Add login page",
        })
        issue_id = issue_resp.json()["id"]
    resp = client.post(f"/api/codex/issues/{issue_id}/plan")
    assert resp.status_code == 200, resp.text
    dag = resp.json()
    assert "nodes" in dag and "edges" in dag
    assert any(n["role_key"] == "product_manager" for n in dag["nodes"])


def test_plan_endpoint_404_when_issue_missing(client):
    resp = client.post("/api/codex/issues/does-not-exist/plan")
    assert resp.status_code == 404


def test_orchestrator_uses_llm_when_runner_returns_valid_json():
    """A pluggable llm_runner is called; valid JSON output is accepted."""
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        agents = await store.list_agents(workspace_id=None)
        agents_by_role = {a.role_key: a for a in agents}
        pm = agents_by_role["product_manager"]

        async def fake_llm(prompt: str) -> str:
            return (
                '{"meta":{"intent":"feature","rationale":"LLM said so"},'
                f'"nodes":[{{"node_key":"pm","agent_id":"{pm.id}","role_key":"product_manager","title":"PM"}}],'
                '"edges":[]}'
            )

        orchestrator = WorkflowOrchestrator(store=store, llm_runner=fake_llm)
        dag = await orchestrator.propose_graph(_make_issue("anything"), use_llm=True)
        assert dag["meta"]["created_by"] == "orchestrator_llm"
        assert [n["role_key"] for n in dag["nodes"]] == ["product_manager"]

    _run(run())


def test_orchestrator_falls_back_to_heuristic_when_llm_returns_garbage():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        async def bad_llm(prompt: str) -> str:
            return "not json at all"

        orchestrator = WorkflowOrchestrator(store=store, llm_runner=bad_llm)
        dag = await orchestrator.propose_graph(
            _make_issue("Implement new feature X"), use_llm=True
        )
        # Heuristic kicked in — feature → full 4-phase pipeline.
        assert [n["role_key"] for n in dag["nodes"]] == [
            "product_manager", "architect", "engineer", "qa",
        ]


    _run(run())
