"""Recover Conductor tasks whose in-memory runner disappeared."""

from __future__ import annotations  # noqa: I001

import asyncio
import os
import json
import logging
from datetime import datetime
from typing import Any

from app.application.conductor_lease import (
    conductor_recovery_enabled,
    get_conductor_lease_owner,
    get_conductor_lease_ttl_s,
    get_conductor_recovery_interval_s,
)
from app.application.conductor_main_loop import (
    _append_event,
    _seal_graph_and_issue_status,
    transition_conductor_phase,
)
from app.application.phase_duration_estimator import get_phase_duration_estimator
from app.application.task_statuses import normalize_task_status
from app.domain.models import ConductorTask

logger = logging.getLogger(__name__)

TERMINAL_ISSUE_STATUSES_FOR_RELAUNCH = frozenset(
    {
        "done",
        "completed",
        "abandoned",
        "failed",
        "merged",
    }
)
ACTIVE_CONDUCTOR_STATUSES_FOR_RELAUNCH = frozenset({"running", "paused"})


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value


def _phase(task: ConductorTask) -> str | None:
    payload = task.payload if isinstance(task.payload, dict) else {}
    phase = payload.get("phase")
    return str(phase) if phase else None


def _detail(task: ConductorTask) -> str | None:
    payload = task.payload if isinstance(task.payload, dict) else {}
    detail = payload.get("detail")
    return str(detail) if detail else None


def _lease_owner_pid(owner: str | None) -> int | None:
    if not owner:
        return None
    parts = owner.split(":", 2)
    if len(parts) < 2 or parts[0] != "pid":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _max_relaunches() -> int:
    """Max orphan-relaunch attempts per issue before the breaker trips."""
    from app.application import timeouts

    return timeouts.conductor_max_relaunches()


async def _count_orphan_stalls(store, issue_id: str) -> int:
    """Count how many times this issue's conductor has been orphaned + stalled.

    Each orphan relaunch leaves behind a ``stalled`` conductor task with reason
    ``orphaned_conductor_runner``. Counting them is a robust, stateless relaunch
    counter that survives across the whole relaunch chain (and across backend
    restarts) without threading a counter through the new loop's creation path.
    """
    list_tasks = getattr(store, "list_conductor_tasks", None)
    if not callable(list_tasks):
        return 0
    stalled = await _maybe_await(list_tasks(status="stalled")) or []
    count = 0
    for t in stalled:
        payload = t.payload if isinstance(t.payload, dict) else {}
        if t.issue_id == issue_id and payload.get("stalled_reason") == "orphaned_conductor_runner":
            count += 1
    return count


def _owner_process_is_alive(owner: str | None) -> bool:
    pid = _lease_owner_pid(owner)
    if pid is None:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_stale(
    task: ConductorTask,
    *,
    now: datetime,
    stale_after_s: int,
    current_owner: str,
    recover_foreign_owner: bool,
) -> bool:
    if task.status != "running":
        return False
    # Never reap a conductor whose loop is still live in THIS process. The
    # background heartbeat keeps the lease fresh, but this is the authoritative
    # in-process liveness signal and guards against any heartbeat lag.
    from app.application.conductor_session_registry import ConductorSessionRegistry

    if task.issue_id and ConductorSessionRegistry.instance().is_conductor_task_alive(
        task.issue_id, task.id
    ):
        return False
    if (
        recover_foreign_owner
        and task.lease_owner
        and task.lease_owner != current_owner
        and not _owner_process_is_alive(task.lease_owner)
    ):
        return True
    if task.lease_expires_at is not None:
        return task.lease_expires_at <= now
    heartbeat_at = task.heartbeat_at or task.updated_at or task.created_at
    if heartbeat_at is None:
        return True
    return (now - heartbeat_at).total_seconds() > stale_after_s


async def recover_orphaned_conductors(
    store,
    *,
    event_bus=None,
    current_owner: str | None = None,
    stale_after_s: int = 180,
    recover_foreign_owner: bool = False,
    auto_restart: bool = False,
    task_dispatcher_fn=None,
) -> int:
    """Mark orphaned running conductor tasks as stalled, then optionally relaunch them.

    `recover_foreign_owner=True` is intended for startup after process reload:
    a task leased by another process-local owner cannot still have its Python
    coroutine in this process.

    `auto_restart=True` relaunches `run_issue_conductor_loop` for each stalled
    task whose issue is still active (not done/abandoned/failed).
    """
    list_tasks = getattr(store, "list_conductor_tasks", None)
    if not callable(list_tasks):
        return 0
    owner = current_owner or get_conductor_lease_owner()
    now = datetime.now()
    tasks = await _maybe_await(list_tasks(status="running"))
    recovered = 0
    for task in tasks or []:
        if not _is_stale(
            task,
            now=now,
            stale_after_s=stale_after_s,
            current_owner=owner,
            recover_foreign_owner=recover_foreign_owner,
        ):
            continue
        await _mark_stalled(
            store,
            event_bus=event_bus,
            task=task,
            now=now,
            current_owner=owner,
        )
        if auto_restart and task.issue_id:
            await _try_relaunch(
                store,
                event_bus=event_bus,
                conductor_task=task,
                task_dispatcher_fn=task_dispatcher_fn,
            )
        recovered += 1
    return recovered


async def _try_relaunch(
    store,
    *,
    event_bus=None,
    conductor_task: ConductorTask,
    task_dispatcher_fn=None,
) -> None:
    """Relaunch the conductor loop for a stalled task's issue."""
    import asyncio  # noqa: F401, I001
    from app.application.conductor_main_loop import run_issue_conductor_loop

    issue_id = conductor_task.issue_id
    if not issue_id:
        return

    load_issue = getattr(store, "load_codex_issue", None)
    if not callable(load_issue):
        return
    # Skip if a live session for this issue already exists in this process.
    from app.application.conductor_session_registry import ConductorSessionRegistry

    if ConductorSessionRegistry.instance().is_alive(issue_id):
        logger.info(
            "conductor relaunch skipped: live session already running for issue %s",
            issue_id,
        )
        return

    issue = await _maybe_await(load_issue(issue_id))
    if issue is None:
        logger.warning("conductor relaunch skipped: issue %s not found", issue_id)
        return

    # Only relaunch for active issues
    if normalize_task_status(issue.status) in TERMINAL_ISSUE_STATUSES_FOR_RELAUNCH:
        logger.info(
            "conductor relaunch skipped: issue %s is in terminal status %s",
            issue_id,
            issue.status,
        )
        return

    # Guard: skip if a newer active conductor already exists for this issue.
    # This prevents double-launch when the watchdog fires multiple times before
    # the first relaunch has registered its conductor_task in the DB.
    load_latest = getattr(store, "load_latest_conductor_task_for_issue", None)
    if callable(load_latest):
        latest = await _maybe_await(load_latest(issue_id))
        if (
            latest is not None
            and latest.id != conductor_task.id
            and normalize_task_status(latest.status) in ACTIVE_CONDUCTOR_STATUSES_FOR_RELAUNCH
        ):
            logger.info(
                "conductor relaunch skipped: active conductor %s already running for issue %s",
                latest.id,
                issue_id,
            )
            return

    # GAP B — relaunch circuit breaker. Each orphan leaves a stalled task behind;
    # if we have already exhausted the relaunch budget for this issue the
    # conductor is crash-looping (launch -> crash -> orphan -> relaunch). Stop
    # relaunching, seal the issue failed, and surface a structured event instead
    # of churning forever. orphan_stalls includes the just-marked current stall,
    # so relaunches already performed == orphan_stalls - 1 (the first stall was
    # the original runner, not a relaunch).
    max_relaunches = _max_relaunches()
    orphan_stalls = await _count_orphan_stalls(store, issue_id)
    relaunches_done = max(0, orphan_stalls - 1)
    if relaunches_done >= max_relaunches:
        logger.error(
            "conductor relaunch circuit breaker tripped for issue %s: %d relaunches done "
            "(max %d) across %d orphan stalls — giving up",
            issue_id,
            relaunches_done,
            max_relaunches,
            orphan_stalls,
        )
        payload = conductor_task.payload if isinstance(conductor_task.payload, dict) else {}
        conductor_task.payload = {
            **payload,
            "relaunch_exhausted": True,
            "relaunch_attempts": relaunches_done,
            "max_relaunches": max_relaunches,
        }
        conductor_task.updated_at = datetime.now()
        await _maybe_await(store.save_conductor_task(conductor_task))
        try:
            await _seal_graph_and_issue_status(
                store=store,
                issue=issue,
                event_bus=event_bus,
                result_status="failed",
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("relaunch-exhausted issue seal failed for %s: %s", issue_id, exc)
        await _append_event(
            event_bus,
            {
                "type": "conductor_relaunch_exhausted",
                "issue_id": issue_id,
                "conductor_task_id": conductor_task.id,
                "relaunch_attempts": relaunches_done,
                "max_relaunches": max_relaunches,
            },
        )
        return

    project_id = issue.project_id
    if not project_id:
        load_session = getattr(store, "load_codex_session", None)
        if callable(load_session) and issue.session_id:
            session = await _maybe_await(load_session(issue.session_id))
            project_id = getattr(session, "project_id", None) if session else None
    if not project_id:
        logger.warning("conductor relaunch skipped: issue %s has no project_id", issue_id)
        return

    now = datetime.now()
    load_graph = getattr(store, "load_workflow_graph_for_issue", None)
    save_graph = getattr(store, "save_workflow_graph", None)
    graph = await _maybe_await(load_graph(issue_id)) if callable(load_graph) else None
    graph_saved = False
    if graph is not None:
        graph.status = "running"
        graph.updated_at = now
        if callable(save_graph):
            try:
                await _maybe_await(save_graph(graph))
            except TypeError:
                await _maybe_await(
                    save_graph(
                        graph,
                        nodes=getattr(graph, "nodes", []) or [],
                        edges=getattr(graph, "edges", []) or [],
                    )
                )
            graph_saved = True
    else:
        from app.domain.models import WorkflowGraph  # noqa: I001
        from uuid import uuid4

        graph = WorkflowGraph(
            id=str(uuid4()),
            issue_id=issue_id,
            dag_json="{}",
            status="running",
            created_by="conductor",
            created_at=now,
            updated_at=now,
            nodes=[],
            edges=[],
        )
    if callable(save_graph) and not graph_saved:
        try:
            await _maybe_await(save_graph(graph))
        except TypeError:
            await _maybe_await(
                save_graph(
                    graph,
                    nodes=getattr(graph, "nodes", []) or [],
                    edges=getattr(graph, "edges", []) or [],
                )
            )

    recovery_context = await _build_relaunch_recovery_context(
        store,
        stalled_task=conductor_task,
        graph=graph,
        relaunches_done=relaunches_done,
        max_relaunches=max_relaunches,
    )

    logger.info("conductor relaunch: starting new loop for issue %s", issue_id)

    def _done_callback(fut: asyncio.Future) -> None:
        exc = fut.exception() if not fut.cancelled() else None
        if exc:
            logger.error(
                "relaunched conductor loop crashed for issue %s: %s",
                issue_id,
                exc,
            )

    handle = await ConductorSessionRegistry.instance().try_start(
        issue_id,
        lambda: run_issue_conductor_loop(
            issue=issue,
            project_id=project_id,
            store=store,
            event_bus=event_bus,
            task_dispatcher_fn=task_dispatcher_fn,
            recovery_context=recovery_context,
        ),
        name=f"conductor-relaunch-{issue_id[:8]}",
    )
    if handle is None:
        logger.info(
            "conductor relaunch skipped: session started concurrently for issue %s",
            issue_id,
        )
        return
    handle.task.add_done_callback(_done_callback)


async def _build_relaunch_recovery_context(
    store,
    *,
    stalled_task: ConductorTask,
    graph,
    relaunches_done: int,
    max_relaunches: int,
) -> str:
    payload = stalled_task.payload if isinstance(stalled_task.payload, dict) else {}
    lines = [
        "\n\n## RECOVERY CONTEXT",
        "This Conductor loop was relaunched after the previous in-memory runner was orphaned.",
        f"Stalled conductor task: {stalled_task.id}",
        f"Previous phase: {payload.get('previous_phase') or payload.get('phase') or 'unknown'}",
        f"Previous detail: {payload.get('previous_detail') or payload.get('detail') or 'unknown'}",
        f"Relaunch attempts used: {relaunches_done}/{max_relaunches}",
        "Resume from persisted state. Do not repeat nodes that are already done; recover unresolved, failed, or conflicted nodes first.",
    ]
    nodes = list(getattr(graph, "nodes", None) or [])
    if nodes:
        lines.append("\nWorkflow node status:")
        for node in nodes[:20]:
            lines.append(
                "- "
                f"{getattr(node, 'node_key', '') or 'unknown'}: "
                f"status={getattr(node, 'status', '') or 'unknown'}, "
                f"task_id={getattr(node, 'task_id', None) or 'none'}, "
                f"retries={getattr(node, 'retries', 0)}/{getattr(node, 'max_retries', 0)}"
            )
        if len(nodes) > 20:
            lines.append(f"- ... {len(nodes) - 20} more nodes omitted")

    list_turns = getattr(store, "list_conductor_turns", None)
    if callable(list_turns) and stalled_task.issue_id:
        try:
            turns = await _maybe_await(list_turns(stalled_task.issue_id, limit=8)) or []
        except Exception:
            turns = []
        if turns:
            lines.append("\nRecent conductor turns:")
            for turn in turns[-8:]:
                kind = getattr(turn, "kind", None) or "unknown"
                turn_index = getattr(turn, "turn_index", None)
                sub_index = getattr(turn, "sub_index", None)
                turn_payload = getattr(turn, "payload", None)
                if not isinstance(turn_payload, dict):
                    turn_payload = {}
                summary = (
                    turn_payload.get("name")
                    or turn_payload.get("status")
                    or turn_payload.get("reason_code")
                    or turn_payload.get("answer")
                    or turn_payload.get("result")
                    or ""
                )
                lines.append(f"- turn={turn_index}.{sub_index} kind={kind}: {str(summary)[:240]}")
    return "\n".join(lines)


async def _mark_stalled(
    store,
    *,
    event_bus,
    task: ConductorTask,
    now: datetime,
    current_owner: str,
) -> None:
    previous_phase = _phase(task)
    previous_detail = _detail(task)
    payload = task.payload if isinstance(task.payload, dict) else {}
    stalled_payload: dict[str, Any] = {
        "status": "stalled",
        "reason": "orphaned_conductor_runner",
        "stalled_at": now.isoformat(),
        "previous_phase": previous_phase,
        "previous_detail": previous_detail,
        "previous_lease_owner": task.lease_owner,
        "current_lease_owner": current_owner,
        "heartbeat_at": task.heartbeat_at.isoformat() if task.heartbeat_at else None,
        "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
    }
    task.payload = {
        **payload,
        "stalled_reason": "orphaned_conductor_runner",
        "stalled_at": now.isoformat(),
        "previous_phase": previous_phase,
        "previous_detail": previous_detail,
        "previous_lease_owner": task.lease_owner,
        "current_lease_owner": current_owner,
    }
    await transition_conductor_phase(
        store=store,
        event_bus=event_bus,
        issue_id=task.issue_id or task.id,
        conductor_task=task,
        phase="stalled",
        detail="orphaned_conductor_runner",
        status="stalled",
        estimator=get_phase_duration_estimator(store),
    )
    task.result_json = json.dumps(stalled_payload, ensure_ascii=False, default=str)
    task.updated_at = now
    await _maybe_await(store.save_conductor_task(task))


async def run_watchdog(store, *, event_bus=None, task_dispatcher_fn=None) -> None:
    """Periodic recovery loop for expired Conductor leases."""
    if not conductor_recovery_enabled():
        logger.info("conductor recovery watchdog disabled via CONDUCTOR_RECOVERY_ENABLED=false")
        return
    interval = get_conductor_recovery_interval_s()
    owner = get_conductor_lease_owner()
    stale_after_s = get_conductor_lease_ttl_s()
    logger.info("conductor recovery watchdog started: scan every %ds", interval)
    try:
        while True:
            try:
                recovered = await recover_orphaned_conductors(
                    store,
                    event_bus=event_bus,
                    current_owner=owner,
                    stale_after_s=stale_after_s,
                    recover_foreign_owner=False,
                    auto_restart=True,
                    task_dispatcher_fn=task_dispatcher_fn,
                )
                if recovered:
                    logger.info("Recovered and relaunched %d orphan conductor task(s)", recovered)
            except Exception as exc:  # noqa: BLE001, RUF100
                logger.exception("conductor recovery scan crashed: %s", exc)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("conductor recovery watchdog stopped")
        raise
