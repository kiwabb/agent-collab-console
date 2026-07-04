"""Recovery watchdog must not reap or duplicate a live in-process conductor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest  # noqa: F401

from app.application import conductor_recovery
from app.application.conductor_lease import get_conductor_lease_owner
from app.application.conductor_recovery import _is_stale, recover_orphaned_conductors
from app.application.conductor_session_registry import ConductorSessionRegistry
from app.domain.models import ConductorTask, WorkflowGraph, WorkflowNode


def _make_ct(*, issue_id: str, status: str = "running", expired: bool = True) -> ConductorTask:
    now = datetime.now()
    return ConductorTask(
        id=str(uuid4()),
        project_id="proj-1",
        task_kind="issue",
        issue_id=issue_id,
        payload={"phase": "awaiting_subagent", "detail": "engineer"},
        status=status,
        lease_owner=get_conductor_lease_owner(),
        heartbeat_at=now - timedelta(seconds=400) if expired else now,
        lease_expires_at=now - timedelta(seconds=200) if expired else now + timedelta(seconds=200),
        created_at=now - timedelta(seconds=400),
        updated_at=now - timedelta(seconds=400),
    )


async def _sleep_forever() -> None:
    await asyncio.Event().wait()


def test_is_stale_false_for_live_same_process_session():
    """An expired lease is NOT stale if the loop is still live in this process."""
    issue_id = "issue-live"
    ct = _make_ct(issue_id=issue_id, expired=True)
    reg = ConductorSessionRegistry.instance()
    # Simulate a live session bound to this exact conductor_task id.
    reg._sessions[issue_id] = MagicMock(
        issue_id=issue_id,
        conductor_task_id=ct.id,
        task=MagicMock(done=MagicMock(return_value=False)),
    )
    try:
        assert (
            _is_stale(
                ct,
                now=datetime.now(),
                stale_after_s=180,
                current_owner=get_conductor_lease_owner(),
                recover_foreign_owner=False,
            )
            is False
        )
    finally:
        reg._sessions.pop(issue_id, None)


def test_is_stale_true_for_expired_lease_without_live_session():
    ct = _make_ct(issue_id="issue-dead", expired=True)
    assert (
        _is_stale(
            ct,
            now=datetime.now(),
            stale_after_s=180,
            current_owner=get_conductor_lease_owner(),
            recover_foreign_owner=False,
        )
        is True
    )


def _make_stall(issue_id: str) -> ConductorTask:
    ct = _make_ct(issue_id=issue_id, status="stalled", expired=True)
    ct.payload = {**ct.payload, "stalled_reason": "orphaned_conductor_runner"}
    return ct


async def test_count_orphan_stalls_filters_by_issue_and_reason():
    issue_id = "issue-count"
    other = _make_stall("issue-other")
    unrelated = _make_ct(issue_id=issue_id, status="stalled", expired=True)  # no orphan reason
    store = MagicMock()
    store.list_conductor_tasks = AsyncMock(
        return_value=[_make_stall(issue_id), _make_stall(issue_id), other, unrelated]
    )
    count = await conductor_recovery._count_orphan_stalls(store, issue_id)
    assert count == 2  # only this issue's orphaned-runner stalls


async def test_relaunch_circuit_breaker_trips_after_max(monkeypatch):
    """A crash-looping issue stops relaunching after the budget and seals failed."""
    monkeypatch.setenv("CONDUCTOR_MAX_RELAUNCHES", "3")
    issue_id = "issue-loop"
    running_ct = _make_ct(issue_id=issue_id, status="running", expired=True)
    # 4 orphan stalls on record == 3 relaunches already done == budget exhausted.
    prior_stalls = [_make_stall(issue_id) for _ in range(4)]

    async def _list(*, status=None):
        if status == "running":
            return [running_ct]
        if status == "stalled":
            return prior_stalls
        return []

    store = MagicMock()
    store.list_conductor_tasks = AsyncMock(side_effect=_list)
    store.save_conductor_task = AsyncMock()
    store.load_codex_issue = AsyncMock(
        return_value=MagicMock(status="open", project_id="proj-1", id=issue_id, session_id="sess-1")
    )
    store.load_latest_conductor_task_for_issue = AsyncMock(return_value=prior_stalls[-1])
    store.load_workflow_graph_for_issue = AsyncMock(return_value=None)
    store.save_codex_issue = AsyncMock()

    events: list[dict] = []
    event_bus = MagicMock()
    event_bus.append = AsyncMock(side_effect=lambda e: events.append(e))

    with (
        patch.object(conductor_recovery, "transition_conductor_phase", new=AsyncMock()),
        patch.object(conductor_recovery, "get_phase_duration_estimator", return_value=MagicMock()),
        patch(
            "app.application.conductor_main_loop.run_issue_conductor_loop", new=AsyncMock()
        ) as relaunch,
    ):
        await recover_orphaned_conductors(
            store,
            event_bus=event_bus,
            current_owner=get_conductor_lease_owner(),
            stale_after_s=180,
            recover_foreign_owner=False,
            auto_restart=True,
        )

    relaunch.assert_not_called()  # breaker tripped — no new loop
    assert any(e.get("type") == "conductor_relaunch_exhausted" for e in events)
    exhausted = next(e for e in events if e.get("type") == "conductor_relaunch_exhausted")
    assert exhausted["relaunch_attempts"] == 3
    assert exhausted["max_relaunches"] == 3
    # Issue sealed failed.
    assert any(e.get("type") == "issue_updated" and e.get("status") == "failed" for e in events)
    store.save_codex_issue.assert_awaited()


async def test_recover_marks_stalled_but_skips_relaunch_when_live_session_exists():
    """A stale OLD row is cleaned up, but no duplicate loop is launched while a
    live session for the same issue still runs."""
    issue_id = "issue-x"
    old_ct = _make_ct(issue_id=issue_id, expired=True)  # superseded, not bound

    store = MagicMock()
    store.list_conductor_tasks = AsyncMock(return_value=[old_ct])
    store.save_conductor_task = AsyncMock()
    store.load_codex_issue = AsyncMock(return_value=MagicMock(status="open", project_id="proj-1"))

    reg = ConductorSessionRegistry.instance()
    # A live session exists for the issue under a DIFFERENT conductor_task id.
    handle = await reg.try_start(issue_id, _sleep_forever)  # noqa: F841
    await reg.bind_conductor_task(issue_id, "ct-NEW-and-live")

    with (
        patch.object(conductor_recovery, "transition_conductor_phase", new=AsyncMock()),
        patch.object(conductor_recovery, "get_phase_duration_estimator", return_value=MagicMock()),
        patch(
            "app.application.conductor_main_loop.run_issue_conductor_loop", new=AsyncMock()
        ) as relaunch,
    ):
        recovered = await recover_orphaned_conductors(
            store,
            current_owner=get_conductor_lease_owner(),
            stale_after_s=180,
            recover_foreign_owner=False,
            auto_restart=True,
        )

    try:
        assert recovered == 1  # the old row was marked stalled
        relaunch.assert_not_called()  # but no duplicate loop launched
        assert reg.is_alive(issue_id)  # the live session is untouched
    finally:
        await reg.stop(issue_id)


async def test_recover_marks_stalled_but_skips_relaunch_for_terminal_issue():
    issue_id = "issue-terminal"
    old_ct = _make_ct(issue_id=issue_id, expired=True)

    store = MagicMock()
    store.list_conductor_tasks = AsyncMock(return_value=[old_ct])
    store.save_conductor_task = AsyncMock()
    store.load_codex_issue = AsyncMock(
        return_value=MagicMock(status="completed", project_id="proj-1", id=issue_id)
    )

    with (
        patch.object(conductor_recovery, "transition_conductor_phase", new=AsyncMock()),
        patch.object(conductor_recovery, "get_phase_duration_estimator", return_value=MagicMock()),
        patch(
            "app.application.conductor_main_loop.run_issue_conductor_loop", new=AsyncMock()
        ) as relaunch,
    ):
        recovered = await recover_orphaned_conductors(
            store,
            current_owner=get_conductor_lease_owner(),
            stale_after_s=180,
            recover_foreign_owner=False,
            auto_restart=True,
        )

    assert recovered == 1
    relaunch.assert_not_called()
    store.save_conductor_task.assert_awaited()


async def test_relaunch_reuses_existing_workflow_graph_nodes():
    issue_id = "issue-graph"
    stalled_ct = _make_stall(issue_id)
    stalled_ct.payload = {
        **stalled_ct.payload,
        "previous_phase": "awaiting_subagent",
        "previous_detail": "engineer",
    }
    existing_node = WorkflowNode(
        id="node-1",
        graph_id="graph-1",
        node_key="engineer",
        agent_id="agent-1",
        status="done",
        task_id="task-1",
    )
    existing_graph = WorkflowGraph(
        id="graph-1",
        issue_id=issue_id,
        dag_json="{}",
        status="stalled",
        nodes=[existing_node],
        edges=[],
    )
    saved_graphs: list[WorkflowGraph] = []
    save_graph_calls: list[tuple[tuple, dict]] = []

    async def _save_graph(graph, *args, **kwargs):
        save_graph_calls.append((args, kwargs))
        saved_graphs.append(graph)

    store = MagicMock()
    store.load_codex_issue = AsyncMock(
        return_value=MagicMock(
            id=issue_id,
            status="open",
            project_id="proj-1",
            session_id="sess-1",
        )
    )
    store.load_latest_conductor_task_for_issue = AsyncMock(return_value=stalled_ct)
    store.list_conductor_tasks = AsyncMock(return_value=[stalled_ct])
    store.save_conductor_task = AsyncMock()
    store.load_workflow_graph_for_issue = AsyncMock(return_value=existing_graph)
    store.save_workflow_graph = AsyncMock(side_effect=_save_graph)
    store.list_conductor_turns = AsyncMock(
        return_value=[
            MagicMock(
                turn_index=1,
                sub_index=0,
                kind="tool_result",
                payload={"name": "dispatch_subagent", "status": "done"},
            )
        ]
    )
    captured: dict[str, str] = {}
    entered = asyncio.Event()

    async def _fake_run_issue_conductor_loop(*args, **kwargs):
        captured["recovery_context"] = kwargs.get("recovery_context", "")
        entered.set()

    with (
        patch.object(conductor_recovery, "transition_conductor_phase", new=AsyncMock()),
        patch.object(conductor_recovery, "get_phase_duration_estimator", return_value=MagicMock()),
        patch("app.application.conductor_main_loop.run_issue_conductor_loop", new=_fake_run_issue_conductor_loop),
    ):
        await conductor_recovery._try_relaunch(
            store,
            conductor_task=stalled_ct,
            event_bus=MagicMock(append=AsyncMock()),
        )
        await asyncio.wait_for(entered.wait(), timeout=1)

    assert saved_graphs
    assert saved_graphs[-1].id == existing_graph.id
    assert saved_graphs[-1].status == "running"
    assert [node.node_key for node in saved_graphs[-1].nodes] == ["engineer"]
    assert saved_graphs[-1].nodes[0].task_id == "task-1"
    assert save_graph_calls[-1] == ((), {})
    recovery_context = captured["recovery_context"]
    assert "## RECOVERY CONTEXT" in recovery_context
    assert f"Stalled conductor task: {stalled_ct.id}" in recovery_context
    assert "Previous phase: awaiting_subagent" in recovery_context
    assert "Previous detail: engineer" in recovery_context
    assert "engineer: status=done, task_id=task-1" in recovery_context
    assert "dispatch_subagent" in recovery_context

    if ConductorSessionRegistry.instance().is_alive(issue_id):
        await ConductorSessionRegistry.instance().stop(issue_id)
