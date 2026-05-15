"""PR6: Replanner — verify scheduler suspends + applies diffs correctly."""
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
from app.domain.models import Agent, CodexIssue, CodexSession


def _run(coro):
    import asyncio as a
    loop = a.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def reseed():
    import app.bootstrap as bootstrap_module
    if bootstrap_module.async_store is not None:
        _run(seed_builtin_agents(bootstrap_module.async_store))
    yield


async def _make_issue(store, title="Add feature X"):
    session = CodexSession(id=str(uuid4()), title="ws", cwd="/tmp", status="idle", created_at=datetime.now())
    await store.save_codex_session(session)
    issue = CodexIssue(id=str(uuid4()), session_id=session.id, title=title, description="", created_at=datetime.now())
    await store.save_codex_issue(issue)
    return issue


def test_replan_after_qa_failure_proposes_refine_loop():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        issue = await _make_issue(store, title="Implement onboarding feature")
        dag = await WorkflowOrchestrator(store=store).propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)
        async def disp(t):
            t.status = "done"
            await store.save_codex_task(t)
        sched = WorkflowScheduler(store=store, task_dispatcher=disp)
        await sched.start_graph(graph.id)
        # Walk graph: PM done → architect done → engineer done → qa run, then fail it.
        for _expected in ["product_manager", "architect", "engineer"]:
            g = await store.load_workflow_graph(graph.id)
            running = next(n for n in g.nodes if n.status == "running")
            t = await store.load_codex_task(running.task_id)
            await sched.on_task_completed(t)
        # Now QA should be running. Fail it.
        g = await store.load_workflow_graph(graph.id)
        qa_node = next(n for n in g.nodes if n.node_key == "qa")
        assert qa_node.status == "running"
        qa_task = await store.load_codex_task(qa_node.task_id)
        qa_task.status = "failed"
        await store.save_codex_task(qa_task)
        await sched.on_task_completed(qa_task)

        # Pending replan should exist with a refine-loop edge proposal.
        pending = await store.list_pending_replans(graph.id)
        assert len(pending) == 1
        diff = pending[0].diff_json
        assert "refine-loop" in diff
        assert "qa" in diff and "engineer" in diff

    _run(run())


def test_confirming_replan_applies_diff_and_resumes():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        issue = await _make_issue(store, "Implement onboarding")
        dag = await WorkflowOrchestrator(store=store).propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)
        async def disp(t):
            t.status = "done"
            await store.save_codex_task(t)
        sched = WorkflowScheduler(store=store, task_dispatcher=disp)
        await sched.start_graph(graph.id)
        # Drive PM → architect → engineer to done.
        for _ in range(3):
            g = await store.load_workflow_graph(graph.id)
            running = next(n for n in g.nodes if n.status == "running")
            t = await store.load_codex_task(running.task_id)
            await sched.on_task_completed(t)
        # Now fail QA.
        g = await store.load_workflow_graph(graph.id)
        qa = next(n for n in g.nodes if n.node_key == "qa")
        qa_task = await store.load_codex_task(qa.task_id)
        qa_task.status = "failed"
        await store.save_codex_task(qa_task)
        await sched.on_task_completed(qa_task)
        pending = await store.list_pending_replans(graph.id)
        replan_id = pending[0].id
        # Confirm — should add the refine-loop edge.
        updated = await sched.apply_replan(replan_id, "confirmed")
        assert any(e.edge_type == "refine-loop" for e in updated.edges)
        # Replan row should now be resolved.
        remaining = await store.list_pending_replans(graph.id)
        assert remaining == []

    _run(run())


def test_rejecting_replan_skips_diff_application():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        issue = await _make_issue(store, "Implement onboarding")
        dag = await WorkflowOrchestrator(store=store).propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)
        async def disp(t):
            t.status = "done"
            await store.save_codex_task(t)
        sched = WorkflowScheduler(store=store, task_dispatcher=disp)
        await sched.start_graph(graph.id)
        for _ in range(3):
            g = await store.load_workflow_graph(graph.id)
            running = next(n for n in g.nodes if n.status == "running")
            t = await store.load_codex_task(running.task_id)
            await sched.on_task_completed(t)
        g = await store.load_workflow_graph(graph.id)
        qa = next(n for n in g.nodes if n.node_key == "qa")
        qa_task = await store.load_codex_task(qa.task_id)
        qa_task.status = "failed"
        await store.save_codex_task(qa_task)
        await sched.on_task_completed(qa_task)
        pending = await store.list_pending_replans(graph.id)
        edges_before = set((e.from_node_key, e.to_node_key, e.edge_type) for e in
                           (await store.load_workflow_graph(graph.id)).edges)
        await sched.apply_replan(pending[0].id, "rejected")
        edges_after = set((e.from_node_key, e.to_node_key, e.edge_type) for e in
                          (await store.load_workflow_graph(graph.id)).edges)
        assert edges_after == edges_before

    _run(run())


def test_engineer_done_does_not_trigger_replan():
    """Engineer is not in the replan-trigger set, so completion proceeds normally."""
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        issue = await _make_issue(store, "Implement onboarding")
        dag = await WorkflowOrchestrator(store=store).propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)
        async def disp(t):
            t.status = "done"
            await store.save_codex_task(t)
        sched = WorkflowScheduler(store=store, task_dispatcher=disp)
        await sched.start_graph(graph.id)
        # PM done — replan with no security_reviewer available → no-op (no changes).
        for _ in range(3):
            g = await store.load_workflow_graph(graph.id)
            running = next(n for n in g.nodes if n.status == "running")
            t = await store.load_codex_task(running.task_id)
            await sched.on_task_completed(t)
        # PM had triggers_replan_on_done=True but the heuristic didn't propose
        # anything because architect+engineer are already in the graph. So
        # the graph should have walked all the way to QA running.
        g = await store.load_workflow_graph(graph.id)
        qa = next(n for n in g.nodes if n.node_key == "qa")
        assert qa.status == "running"
        # Engineer node has done status.
        eng = next(n for n in g.nodes if n.node_key == "engineer")
        assert eng.status == "done"

    _run(run())


def test_replan_diff_rejects_removing_done_nodes():
    import app.bootstrap as bootstrap_module
    store = bootstrap_module.async_store

    async def run():
        issue = await _make_issue(store, "x")
        dag = await WorkflowOrchestrator(store=store).propose_graph(issue)
        graph = await materialize_graph_from_dag(store, issue.id, dag)
        async def disp(t):
            t.status = "done"
            await store.save_codex_task(t)
        sched = WorkflowScheduler(store=store, task_dispatcher=disp)
        await sched.start_graph(graph.id)
        # Mark architect done so it's terminal.
        g = await store.load_workflow_graph(graph.id)
        running = next(n for n in g.nodes if n.status == "running")
        t = await store.load_codex_task(running.task_id)
        await sched.on_task_completed(t)
        g = await store.load_workflow_graph(graph.id)
        done_keys = {n.node_key for n in g.nodes if n.status == "done"}
        assert done_keys
        # Manually apply a diff that tries to remove a done node.
        evil_diff = {
            "added_nodes": [],
            "added_edges": [],
            "removed_node_keys": list(done_keys),
            "removed_edge_ids": [],
        }
        await sched._apply_diff_to_graph(graph.id, evil_diff)
        # Done nodes must still be there.
        after = await store.load_workflow_graph(graph.id)
        remaining = {n.node_key for n in after.nodes}
        assert remaining.issuperset(done_keys)

    _run(run())
