"""PR3: WorkflowScheduler + graph endpoints integration."""
from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from app.application.agent_seed import seed_builtin_agents
from app.application.workflow_orchestrator import WorkflowOrchestrator
from app.application.workflow_scheduler import (
    WorkflowScheduler,
    materialize_graph_from_dag,
)
from app.domain.models import CodexIssue, CodexSession


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


async def _make_issue_in_store(store, title="Feat foo", *, plan_first_pm: bool = True) -> CodexIssue:
    session = CodexSession(
        id=str(uuid4()),
        title="ws",
        cwd="/tmp",
        status="idle",
        created_at=datetime.now(),
        settings={"plan_first_pm": plan_first_pm},
    )
    await store.save_codex_session(session)
    issue = CodexIssue(id=str(uuid4()), session_id=session.id, title=title,
                     description="", created_at=datetime.now())
    await store.save_codex_issue(issue)
    return issue


def test_materialize_graph_persists_nodes_and_edges():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        issue = await _make_issue_in_store(store)
        orchestrator = WorkflowOrchestrator(store=store)
        dag = await orchestrator.propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag, created_by="user")
        loaded = await store.load_workflow_graph(graph.id)
        assert loaded is not None
        assert len(loaded.nodes) == len(dag["nodes"])
        assert len(loaded.edges) == len(dag["edges"])
        assert all(n.status == "pending" for n in loaded.nodes)

    _run(run())


def test_scheduler_marks_first_node_ready_and_dispatches():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    dispatched: list[str] = []

    def fake_dispatcher(task):
        dispatched.append(task.id)
        # Don't actually run; the test will manually drive the task to done.

    async def run():
        issue = await _make_issue_in_store(store, title="Implement feature X")
        orchestrator = WorkflowOrchestrator(store=store)
        dag = await orchestrator.propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)
        scheduler = WorkflowScheduler(store=store, task_dispatcher=fake_dispatcher)
        graph = await scheduler.start_graph(graph.id)
        # The first node (product_manager for "feature") must be running, downstream blocked.
        assert graph.status == "running"
        first = next(n for n in graph.nodes if n.node_key == "product_manager")
        assert first.status == "running"
        downstream = [n for n in graph.nodes if n.node_key != "product_manager"]
        assert all(n.status == "blocked" for n in downstream)
        assert len(dispatched) == 1

    _run(run())


def test_scheduler_walks_chain_to_completion_via_task_callback():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        issue = await _make_issue_in_store(store, title="Refactor user service")
        orchestrator = WorkflowOrchestrator(store=store)
        dag = await orchestrator.propose_graph(issue)  # refactor → architect + engineer
        graph = await materialize_graph_from_dag(store, issue.id, dag)

        # Dispatcher immediately marks the task done — simulates an extremely fast runner.
        async def auto_done_dispatcher(task):
            task.status = "done"
            task.updated_at = datetime.now()
            await store.save_codex_task(task)

        scheduler = WorkflowScheduler(store=store, task_dispatcher=auto_done_dispatcher)
        await scheduler.start_graph(graph.id)
        # Step 1 task is created + marked done; notify scheduler so it can walk on.
        node_arch = (await store.load_workflow_graph(graph.id)).nodes[0]
        assert node_arch.node_key == "architect"
        running_task = await store.load_codex_task(node_arch.task_id)
        await scheduler.on_task_completed(running_task)

        # Now engineer node should be running.
        g = await store.load_workflow_graph(graph.id)
        node_eng = next(n for n in g.nodes if n.node_key == "engineer")
        assert node_eng.status == "running"
        # Complete engineer too.
        eng_task = await store.load_codex_task(node_eng.task_id)
        await scheduler.on_task_completed(eng_task)
        final = await store.load_workflow_graph(graph.id)
        assert final.status == "done"
        assert all(n.status == "done" for n in final.nodes)

    _run(run())


def test_scheduler_pauses_for_plan_approval_and_resumes_after_approval():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    dispatched: list[str] = []

    async def auto_done_dispatcher(task):
        dispatched.append(task.id)
        task.status = "done"
        task.updated_at = datetime.now()
        await store.save_codex_task(task)

    async def run():
        issue = await _make_issue_in_store(store, title="Implement feature X")
        orchestrator = WorkflowOrchestrator(store=store)
        dag = await orchestrator.propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)

        scheduler = WorkflowScheduler(store=store, task_dispatcher=auto_done_dispatcher)
        await scheduler.start_graph(graph.id)
        graph = await store.load_workflow_graph(graph.id)
        pm_node = next(n for n in graph.nodes if n.node_key == "product_manager")
        assert pm_node.status == "running"
        assert len(dispatched) == 1

        pm_task = await store.load_codex_task(pm_node.task_id)
        await scheduler.on_task_completed(pm_task)

        paused_issue = await store.load_codex_issue(issue.id)
        assert paused_issue is not None
        assert paused_issue.status == "awaiting_approval"
        assert paused_issue.review_comment
        paused_graph = await store.load_workflow_graph(graph.id)
        architect_node = next(n for n in paused_graph.nodes if n.node_key == "architect")
        assert architect_node.status != "running"
        assert len(dispatched) == 1

        paused_issue.status = "in_progress"
        await store.save_codex_issue(paused_issue)
        await scheduler.settle(graph.id)

        resumed_graph = await store.load_workflow_graph(graph.id)
        architect_node = next(n for n in resumed_graph.nodes if n.node_key == "architect")
        assert architect_node.status == "running"
        assert len(dispatched) == 2

    _run(run())


def test_scheduler_can_disable_plan_first_gate():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    dispatched: list[str] = []

    async def auto_done_dispatcher(task):
        dispatched.append(task.id)
        task.status = "done"
        task.updated_at = datetime.now()
        await store.save_codex_task(task)

    async def run():
        issue = await _make_issue_in_store(store, title="Fast path feature", plan_first_pm=False)
        orchestrator = WorkflowOrchestrator(store=store)
        dag = await orchestrator.propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)

        scheduler = WorkflowScheduler(store=store, task_dispatcher=auto_done_dispatcher)
        await scheduler.start_graph(graph.id)
        pm_node = next(n for n in (await store.load_workflow_graph(graph.id)).nodes if n.node_key == "product_manager")
        pm_task = await store.load_codex_task(pm_node.task_id)
        await scheduler.on_task_completed(pm_task)

        next_graph = await store.load_workflow_graph(graph.id)
        architect_node = next(n for n in next_graph.nodes if n.node_key == "architect")
        assert architect_node.status == "running"
        assert len(dispatched) >= 2
        saved_issue = await store.load_codex_issue(issue.id)
        assert saved_issue is not None
        assert saved_issue.status != "awaiting_approval"

    _run(run())


def test_conductor_spawn_specialist_adds_and_dispatches_node(monkeypatch):
    import app.bootstrap as bootstrap_module
    from app.application.conductor_supervisor import ConductorSupervisor
    store = bootstrap_module.async_store

    monkeypatch.setenv("CONDUCTOR_AUTONOMY", "autonomous")

    async def fake_observe(self, **kwargs):
        return {
            "action": "spawn_specialist",
            "reason": "Auth flow needs focused security review",
            "role_key": "security_reviewer",
            "prompt": "Review the authentication flow for security risks.",
        }

    monkeypatch.setattr(ConductorSupervisor, "observe", fake_observe)
    dispatched: list = []

    async def auto_done_dispatcher(task):
        dispatched.append(task)
        task.status = "done"
        task.updated_at = datetime.now()
        await store.save_codex_task(task)

    async def run():
        issue = await _make_issue_in_store(
            store,
            title="Secure login flow",
            plan_first_pm=False,
        )
        agents = {a.role_key: a for a in await store.list_agents(workspace_id=None)}
        dag = {
            "nodes": [
                {
                    "node_key": "architect",
                    "agent_id": agents["architect"].id,
                    "role_key": "architect",
                    "title": "Architect",
                }
            ],
            "edges": [],
        }
        graph = await materialize_graph_from_dag(store, issue.id, dag)
        scheduler = WorkflowScheduler(store=store, task_dispatcher=auto_done_dispatcher)

        await scheduler.start_graph(graph.id)
        first_task = dispatched[0]
        await scheduler.on_task_completed(first_task)

        updated = await store.load_workflow_graph(graph.id)
        spawned_node = next(
            n for n in updated.nodes if n.node_key.startswith("specialist_security_reviewer")
        )
        assert spawned_node.status == "running"
        assert spawned_node.prompt_override == "Review the authentication flow for security risks."
        assert any(
            e.from_node_key == "architect" and e.to_node_key == spawned_node.node_key
            for e in updated.edges
        )
        spawned_task = dispatched[-1]
        assert spawned_task.role == "specialist:security_reviewer"
        assert spawned_task.prompt == "Review the authentication flow for security risks."

    _run(run())


def test_conductor_spawn_custom_registers_agent_and_dispatches_node(monkeypatch):
    import app.bootstrap as bootstrap_module
    from app.application.conductor_supervisor import ConductorSupervisor
    store = bootstrap_module.async_store

    monkeypatch.setenv("CONDUCTOR_AUTONOMY", "autonomous")

    async def fake_observe(self, **kwargs):
        return {
            "action": "spawn_custom",
            "reason": "Need a focused migration checklist",
            "name": "Migration Checklist",
            "prompt": "Create a migration checklist for this change.",
            "schema": {"type": "object", "properties": {"checklist": {"type": "array"}}},
        }

    monkeypatch.setattr(ConductorSupervisor, "observe", fake_observe)
    dispatched: list = []

    async def auto_done_dispatcher(task):
        dispatched.append(task)
        task.status = "done"
        task.updated_at = datetime.now()
        await store.save_codex_task(task)

    async def run():
        issue = await _make_issue_in_store(
            store,
            title="Database migration",
            plan_first_pm=False,
        )
        agents = {a.role_key: a for a in await store.list_agents(workspace_id=None)}
        graph = await materialize_graph_from_dag(
            store,
            issue.id,
            {
                "nodes": [
                    {
                        "node_key": "architect",
                        "agent_id": agents["architect"].id,
                        "role_key": "architect",
                        "title": "Architect",
                    }
                ],
                "edges": [],
            },
        )
        scheduler = WorkflowScheduler(store=store, task_dispatcher=auto_done_dispatcher)

        await scheduler.start_graph(graph.id)
        await scheduler.on_task_completed(dispatched[0])

        custom_agents = await store.list_agents(workspace_id=None, role_key="custom:migration_checklist")
        assert custom_agents
        assert custom_agents[0].agent_tier == "custom"
        updated = await store.load_workflow_graph(graph.id)
        spawned_node = next(
            n for n in updated.nodes if n.node_key.startswith("custom_migration_checklist")
        )
        assert spawned_node.status == "running"
        spawned_task = dispatched[-1]
        assert spawned_task.role == "custom:migration_checklist"
        assert spawned_task.executor == "claude"

    _run(run())


def test_conductor_inject_context_updates_next_node_prompt(monkeypatch):
    import app.bootstrap as bootstrap_module
    from app.application.conductor_supervisor import ConductorSupervisor
    store = bootstrap_module.async_store

    monkeypatch.setenv("CONDUCTOR_AUTONOMY", "autonomous")

    async def fake_observe(self, **kwargs):
        return {
            "action": "inject_context",
            "reason": "Architect needs a constraint from PM.",
            "target_node_key": "architect",
            "context_message": "Preserve the existing REST API contract.",
        }

    monkeypatch.setattr(ConductorSupervisor, "observe", fake_observe)
    dispatched: list = []

    async def auto_done_dispatcher(task):
        dispatched.append(task)
        task.status = "done"
        task.updated_at = datetime.now()
        await store.save_codex_task(task)

    async def run():
        issue = await _make_issue_in_store(
            store,
            title="Refactor auth API",
            plan_first_pm=False,
        )
        agents = {a.role_key: a for a in await store.list_agents(workspace_id=None)}
        graph = await materialize_graph_from_dag(
            store,
            issue.id,
            {
                "nodes": [
                    {"node_key": "product_manager", "agent_id": agents["product_manager"].id},
                    {"node_key": "architect", "agent_id": agents["architect"].id},
                ],
                "edges": [
                    {"from_node_key": "product_manager", "to_node_key": "architect"},
                ],
            },
        )
        scheduler = WorkflowScheduler(store=store, task_dispatcher=auto_done_dispatcher)

        await scheduler.start_graph(graph.id)
        await scheduler.on_task_completed(dispatched[0])

        architect_task = dispatched[-1]
        assert architect_task.role == "architect"
        assert "[CONDUCTOR CONTEXT]" in architect_task.prompt
        assert "Preserve the existing REST API contract." in architect_task.prompt
        assert "Refactor auth API" in architect_task.prompt
        state = await store.load_conductor_state(issue.id)
        assert state is not None
        assert state.pending_dispatches_json == "[]"

    _run(run())


def test_conductor_dispatch_next_prioritizes_blocked_node(monkeypatch):
    import app.bootstrap as bootstrap_module
    from app.application.conductor_supervisor import ConductorSupervisor
    store = bootstrap_module.async_store

    monkeypatch.setenv("CONDUCTOR_AUTONOMY", "autonomous")

    async def fake_observe(self, **kwargs):
        return {
            "action": "dispatch_next",
            "reason": "Security should run immediately.",
            "target_node_key": "specialist_security_reviewer",
            "prompt_override": "Review auth before implementation continues.",
        }

    monkeypatch.setattr(ConductorSupervisor, "observe", fake_observe)
    dispatched: list = []

    async def auto_done_dispatcher(task):
        dispatched.append(task)
        task.status = "done"
        task.updated_at = datetime.now()
        await store.save_codex_task(task)

    async def run():
        issue = await _make_issue_in_store(
            store,
            title="Implement secure login",
            plan_first_pm=False,
        )
        agents = {a.role_key: a for a in await store.list_agents(workspace_id=None)}
        graph = await materialize_graph_from_dag(
            store,
            issue.id,
            {
                "nodes": [
                    {"node_key": "architect", "agent_id": agents["architect"].id},
                    {
                        "node_key": "specialist_security_reviewer",
                        "agent_id": agents["specialist:security_reviewer"].id,
                    },
                    {"node_key": "engineer", "agent_id": agents["engineer"].id},
                ],
                "edges": [
                    {"from_node_key": "architect", "to_node_key": "engineer"},
                    {"from_node_key": "engineer", "to_node_key": "specialist_security_reviewer"},
                ],
            },
        )
        scheduler = WorkflowScheduler(store=store, task_dispatcher=auto_done_dispatcher)

        await scheduler.start_graph(graph.id)
        await scheduler.on_task_completed(dispatched[0])

        prioritized_task = dispatched[-1]
        assert prioritized_task.role == "specialist:security_reviewer"
        assert prioritized_task.prompt == "Review auth before implementation continues."

    _run(run())


def test_approve_plan_endpoint_resumes_scheduler(client, monkeypatch):
    import app.bootstrap as bootstrap_module
    from app.application.workflow_scheduler import WorkflowScheduler

    store = bootstrap_module.async_store
    calls: list[str] = []

    async def fake_settle(self, graph_id):
        calls.append(graph_id)
        return await self._require_graph(graph_id)

    monkeypatch.setattr(WorkflowScheduler, "settle", fake_settle)

    async def run():
        issue = await _make_issue_in_store(store, title="Endpoint approval")
        orchestrator = WorkflowOrchestrator(store=store)
        dag = await orchestrator.propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)

        issue = await store.load_codex_issue(issue.id)
        assert issue is not None
        issue.status = "awaiting_approval"
        issue.review_comment = "- confirm PRD"
        await store.save_codex_issue(issue)

        response = client.post(
            f"/api/codex/issues/{issue.id}/approve-plan",
            json={"review_comment": "- confirm PRD\n- continue to Architect"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "in_progress"
        assert payload["review_comment"] == "- confirm PRD\n- continue to Architect"
        assert calls == [graph.id]

        saved = await store.load_codex_issue(issue.id)
        assert saved is not None
        assert saved.status == "in_progress"

    _run(run())


def test_graph_endpoints_save_get_start(client):
    """End-to-end: hit /plan, save, get, start via FastAPI."""
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def setup():
        return await _make_issue_in_store(store, title="Add export endpoint")

    issue = _run(setup())

    plan_resp = client.post(f"/api/codex/issues/{issue.id}/plan")
    assert plan_resp.status_code == 200
    dag = plan_resp.json()

    save_resp = client.post(f"/api/codex/issues/{issue.id}/graph", json={"dag": dag})
    assert save_resp.status_code == 201, save_resp.text
    saved = save_resp.json()
    assert saved["status"] == "draft"
    assert len(saved["nodes"]) == len(dag["nodes"])

    get_resp = client.get(f"/api/codex/issues/{issue.id}/graph")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == saved["id"]

    start_resp = client.post(f"/api/codex/issues/{issue.id}/graph/start")
    assert start_resp.status_code == 200
    started = start_resp.json()
    # The graph attempted to dispatch the first node. In test mode the
    # real CodexTaskRunner is wired but the ephemeral issue lacks a
    # workspace_path — the scheduler should record this as a failure
    # rather than crashing.
    statuses = {n["node_key"]: n["status"] for n in started["nodes"]}
    assert statuses["product_manager"] in {"running", "done", "failed"}


def test_graph_save_rejects_unknown_agent(client):
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store
    issue = _run(_make_issue_in_store(store, title="Bad DAG"))
    bad_dag = {
        "meta": {},
        "nodes": [{"node_key": "x", "agent_id": "definitely-not-real", "role_key": "y"}],
        "edges": [],
    }
    resp = client.post(f"/api/codex/issues/{issue.id}/graph", json={"dag": bad_dag})
    assert resp.status_code == 400
