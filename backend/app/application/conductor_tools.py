"""Tool registry for the ProjectConductor loop."""

from __future__ import annotations  # noqa: I001

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable  # noqa: UP035
from uuid import uuid4

from app.application.project_conductor import ProjectConductor
from app.application.task_statuses import (
    TASK_FAILURE_STATUSES,
    TASK_SUCCESS_STATUSES,
    is_task_success_status,
    is_task_terminal_status,
    normalize_task_status,
)
from app.application.task_dispatcher import normalize_role


ToolCallable = Callable[[dict[str, Any]], Awaitable[Any]]
ToolStatusCallback = Callable[[str, str | None], Awaitable[None] | None]

PLANNING_ONLY_FINALIZE_ROLES = {"product_manager", "architect"}
IMPLEMENTATION_FINALIZE_ROLES = {
    "engineer",
    "engineer_backend",
    "engineer_frontend",
    "operations_engineer",
    "specialist:doc_writer",
}
VERIFICATION_FINALIZE_ROLES = {
    "qa",
    "specialist:accessibility_reviewer",
    "specialist:api_contract_checker",
    "specialist:code_reviewer",
    "specialist:dependency_auditor",
    "specialist:i18n_checker",
    "specialist:performance_reviewer",
    "specialist:security_reviewer",
}

_DISPATCH_START_LOCKS_BY_ISSUE: dict[str, asyncio.Lock] = {}


def _dispatch_start_lock_for_issue(issue_id: str) -> asyncio.Lock:
    lock = _DISPATCH_START_LOCKS_BY_ISSUE.get(issue_id)
    if lock is None:
        lock = asyncio.Lock()
        _DISPATCH_START_LOCKS_BY_ISSUE[issue_id] = lock
    return lock


def _max_dispatches_per_role() -> int:
    """GAP G: max times the Conductor may dispatch the same role for one issue
    before the tool returns `retries_exhausted`. Allows the initial run plus a
    few reworks (e.g. engineer after QA failure) without unbounded looping."""
    from app.application import timeouts

    return timeouts.conductor_max_dispatches_per_role()


@dataclass(frozen=True)
class ConductorToolRegistry:
    definitions: list[dict[str, Any]]
    tools: dict[str, ToolCallable]


def build_conductor_tools(
    *,
    project_id: str,
    store,
    event_bus=None,
    task_dispatcher_fn=None,
    issue_id: str | None = None,
    on_status: ToolStatusCallback | None = None,
    worktree_manager=None,
) -> ConductorToolRegistry:
    conductor = ProjectConductor(project_id=project_id, store=store, event_bus=event_bus)

    def _resolve_worktree_manager():
        """Per-agent worktree isolation needs the shared WorktreeManager. Tests
        inject one explicitly; production falls back to the bootstrap singleton.
        Imported lazily so importing this module never pulls in bootstrap."""
        if worktree_manager is not None:
            return worktree_manager
        from app.bootstrap import worktree_manager as _wm

        return _wm

    async def retrieve_cold_memory(tool_input: dict[str, Any]) -> dict[str, Any]:
        query = str(tool_input.get("query") or "")
        top_k = int(tool_input.get("top_k") or 3)
        return {"memories": await conductor.retrieve_cold(query, top_k=max(1, min(top_k, 10)))}

    async def _governance_failure(
        *,
        tool: str,
        gate: str,
        error: Exception,
        issue_ref: str | None,
    ) -> dict[str, Any]:
        detail = f"{type(error).__name__}: {error}"
        await _emit(
            event_bus,
            "conductor_tool",
            {
                "tool": tool,
                "issue_id": issue_ref,
                "status": "governance_unavailable",
                "gate": gate,
                "error": detail,
            },
        )
        return {
            "status": "failed",
            "gate": gate,
            "error": (
                f"{gate} governance could not be evaluated; refusing to dispatch "
                "until the required state is readable again"
            ),
            "details": detail,
        }

    async def _compute_budget_status(issue, *, tool: str):
        from app.application.budget_service import compute_issue_budget_status

        try:
            return await compute_issue_budget_status(store, issue), None
        except Exception as exc:  # noqa: BLE001, RUF100
            failure = await _governance_failure(
                tool=tool,
                gate="budget",
                error=exc,
                issue_ref=issue.id,
            )
            return None, failure

    async def _budget_exceeded_result(issue, budget_status, *, tool: str) -> dict[str, Any] | None:
        if not budget_status.over_budget:
            return None
        remaining = budget_status.remaining_usd
        payload = {
            "tool": tool,
            "issue_id": issue.id,
            "status": "budget_exceeded",
            "spent_usd": round(budget_status.spent_usd, 6),
            "reserved_usd": round(budget_status.reserved_usd, 6),
            "budget_usd": round(budget_status.budget_usd, 6),
            "remaining_usd": None if remaining is None else round(remaining, 6),
        }
        await _emit(event_bus, "conductor_tool", payload)
        return {
            "status": "budget_exceeded",
            "error": (
                "issue budget is exhausted; do not dispatch new subagents. "
                "Finalize with the current result, ask the user for more budget, "
                "or choose a no-cost recovery path."
            ),
            "budget": {
                "spent_usd": payload["spent_usd"],
                "reserved_usd": payload["reserved_usd"],
                "budget_usd": payload["budget_usd"],
                "remaining_usd": payload["remaining_usd"],
            },
        }

    async def _check_budget_gate(issue, *, tool: str) -> dict[str, Any] | None:
        """Hard gate new dispatches once issue spend reaches its ceiling."""
        budget_status, failure = await _compute_budget_status(issue, tool=tool)
        if failure is not None:
            return failure
        assert budget_status is not None
        return await _budget_exceeded_result(issue, budget_status, tool=tool)

    async def _load_graph_for_governance(*, tool: str, gate: str):
        if not issue_id:
            return None, None
        try:
            return await store.load_workflow_graph_for_issue(issue_id), None
        except Exception as exc:  # noqa: BLE001, RUF100
            failure = await _governance_failure(
                tool=tool,
                gate=gate,
                error=exc,
                issue_ref=issue_id,
            )
            return None, failure

    async def _check_redispatch_budget(role: str, *, tool: str) -> dict[str, Any] | None:
        """GAP G: bound re-dispatch. Each dispatch of a role adds a graph node
        (role, role#1, role#2…); past the budget the Conductor is stuck in a
        rework loop. Returns a terminal `retries_exhausted` dict when exhausted,
        else None. Shared by dispatch_subagent and dispatch_batch."""
        role = normalize_role(role)
        if not role or not issue_id:
            return None
        graph, failure = await _load_graph_for_governance(
            tool=tool,
            gate="redispatch_budget",
        )
        if failure is not None:
            return failure
        if graph is None:
            return None
        same_role = sum(
            1
            for n in graph.nodes
            if n.node_key == role or n.node_key.startswith(f"{role}#")
        )
        max_dispatches = _max_dispatches_per_role()
        if same_role < max_dispatches:
            return None
        await _emit(
            event_bus,
            "conductor_tool",
            {
                "tool": tool,
                "role": role,
                "status": "retries_exhausted",
                "dispatches": same_role,
            },
        )
        return {
            "status": "retries_exhausted",
            "role": role,
            "dispatches": same_role,
            "max_dispatches": max_dispatches,
            "note": (
                f"role '{role}' already dispatched {same_role} times "
                f"(max {max_dispatches}); do not re-dispatch it"
            ),
        }

    async def _check_batch_redispatch_budget(
        specs: list[dict[str, Any]],
        *,
        tool: str,
    ) -> dict[str, Any] | None:
        """Atomically reject batch fan-out that would exceed per-role limits."""
        graph, failure = await _load_graph_for_governance(
            tool=tool,
            gate="redispatch_budget",
        )
        if failure is not None:
            return failure
        if graph is None:
            return None
        max_dispatches = _max_dispatches_per_role()
        existing_by_role: dict[str, int] = {}
        for node in graph.nodes:
            node_key = str(node.node_key or "")
            base_role = normalize_role(node_key.split("#", 1)[0])
            if base_role:
                existing_by_role[base_role] = existing_by_role.get(base_role, 0) + 1
        requested_by_role: dict[str, int] = {}
        for spec in specs:
            role = normalize_role(str(spec.get("role") or ""))
            if role:
                requested_by_role[role] = requested_by_role.get(role, 0) + 1
        exhausted = [
            {
                "role": role,
                "dispatches": existing_by_role.get(role, 0),
                "requested": requested,
                "max_dispatches": max_dispatches,
            }
            for role, requested in requested_by_role.items()
            if existing_by_role.get(role, 0) + requested > max_dispatches
        ]
        if not exhausted:
            return None
        await _emit(
            event_bus,
            "conductor_tool",
            {
                "tool": tool,
                "status": "retries_exhausted",
                "roles": exhausted,
            },
        )
        return {
            "status": "retries_exhausted",
            "error": "batch would exceed per-role dispatch limits; narrow the batch or choose different roles",
            "roles": exhausted,
        }

    async def _check_finalize_success_gate() -> dict[str, Any] | None:
        """Reject model-reported success when the persisted graph is not clean.

        ``finalize_task`` is the Conductor's terminal switch. The model can
        decide *when* to request completion, but the backend owns the invariant
        that a successful issue cannot have unfinished, failed, or conflicted
        workflow nodes.
        """
        graph, failure = await _load_graph_for_governance(
            tool="finalize_task",
            gate="workflow_graph",
        )
        if failure is not None:
            return failure
        if graph is None:
            return {
                "status": "failed",
                "reason": "workflow graph is missing; cannot finalize as done",
            }
        nodes = list(graph.nodes)
        if not nodes:
            return {
                "status": "failed",
                "reason": "workflow graph has no nodes; cannot finalize as done",
            }
        completed_statuses = TASK_SUCCESS_STATUSES
        allowed_done_statuses = {*completed_statuses, "skipped"}
        blocker_statuses = TASK_FAILURE_STATUSES | {
            "blocked",
            "rework",
            "conflict",
            "merge_conflict",
            "artifact_invalid",
            "retries_exhausted",
            "timeout",
            "timed_out",
        }
        unfinished_statuses = {
            "pending",
            "queued",
            "running",
            "responding",
            "waiting",
            "waiting_for_help",
            "waiting_for_specialist",
            "ready_to_resume",
            "awaiting_review",
            "awaiting_approval",
            "awaiting_merge",
        }
        blocking_nodes: list[dict[str, Any]] = []
        has_completed_work = False
        completed_base_roles: set[str] = set()
        for node in nodes:
            node_status = normalize_task_status(node.status)
            node_key = str(node.node_key or "")
            base_role = normalize_role(node_key.split("#", 1)[0])
            if node_status in allowed_done_statuses:
                if node_status in completed_statuses:
                    has_completed_work = True
                    if base_role:
                        completed_base_roles.add(base_role)
                continue
            if node_status in blocker_statuses or node_status in unfinished_statuses:
                blocking_nodes.append({"node_key": node_key, "status": node_status or "unknown"})
            elif node_status:
                blocking_nodes.append({"node_key": node_key, "status": node_status})
        if blocking_nodes:
            return {
                "status": "failed",
                "reason": "workflow graph still has unresolved nodes; cannot finalize as done",
                "blocking_nodes": blocking_nodes[:10],
            }
        if not has_completed_work:
            return {
                "status": "failed",
                "reason": "workflow graph has no completed work node; cannot finalize as done",
            }
        if completed_base_roles and completed_base_roles.issubset(
            PLANNING_ONLY_FINALIZE_ROLES
        ):
            return {
                "status": "failed",
                "reason": (
                    "workflow graph only has planning/design completed; cannot finalize as done "
                    "without implementation or delivery evidence"
                ),
            }
        if completed_base_roles and completed_base_roles.issubset(VERIFICATION_FINALIZE_ROLES):
            return {
                "status": "failed",
                "reason": (
                    "workflow graph only has verification completed; cannot finalize as done "
                    "without implementation or delivery evidence"
                ),
            }
        has_implementation = bool(
            completed_base_roles.intersection(IMPLEMENTATION_FINALIZE_ROLES)
        )
        has_verification = bool(completed_base_roles.intersection(VERIFICATION_FINALIZE_ROLES))
        if completed_base_roles and not has_implementation:
            recognized_roles = (
                PLANNING_ONLY_FINALIZE_ROLES
                | IMPLEMENTATION_FINALIZE_ROLES
                | VERIFICATION_FINALIZE_ROLES
            )
            unclassified_roles = sorted(completed_base_roles - recognized_roles)
            return {
                "status": "failed",
                "reason": (
                    "workflow graph has no recognized implementation or delivery evidence; "
                    "cannot finalize as done"
                ),
                "unclassified_roles": unclassified_roles,
            }
        if has_implementation and not has_verification:
            return {
                "status": "failed",
                "reason": (
                    "workflow graph has implementation completed but no verification node completed; "
                    "cannot finalize as done"
                ),
            }
        return None

    async def _run_single_dispatch(
        *,
        issue,
        role: str,
        prompt_override: str | None,
        prev_node_key: str | None,
        agent_worktree_path: str | None,
        tool: str,
        batch_key: str | None = None,
        dispatch_start_lock: asyncio.Lock | None = None,
        pre_dispatch_check: Callable[[], Awaitable[dict[str, Any] | None]] | None = None,
    ) -> dict[str, Any]:
        """Run one subagent dispatch end-to-end: acquire a per-role concurrency
        slot, dispatch the role task, then activity-aware wait for completion.

        This is the single source of truth for the dispatch lifecycle, shared by
        both dispatch_subagent (serial path, agent_worktree_path=None → shared
        issue worktree) and dispatch_batch (parallel path, agent_worktree_path
        set → isolated per-agent worktree). Returns the subagent result dict or a
        structured status/error dict (role_busy / timeout / value error)."""
        from datetime import datetime  # noqa: I001
        from app.application import task_activity, timeouts
        from app.application import task_dispatcher as task_dispatcher_module
        from app.application.role_concurrency import RoleConcurrencyLimiter
        from app.application.task_completion_registry import TaskCompletionRegistry

        detail = role or prev_node_key or "subagent"

        # GAP: enforce MAX_CONCURRENT_INSTANCES_PER_ROLE. Acquire a process-wide
        # slot for this role BEFORE dispatching, so we never create a task/node
        # we can't actually run within the cap. The slot is held for the whole
        # subagent run and released when wait_for_active returns or times out.
        # If every slot is busy past role_slot_wait_s, return a structured
        # `role_busy` so the Conductor re-plans instead of blocking forever.
        limiter = RoleConcurrencyLimiter.instance()
        role = normalize_role(role)
        slot_role = role or "subagent"
        slot_wait = timeouts.role_slot_wait_s()
        async with limiter.slot(slot_role, timeout=slot_wait) as acquired:
            if not acquired:
                limit = timeouts.max_concurrent_instances_per_role()
                await _emit(
                    event_bus,
                    "conductor_tool",
                    {
                        "tool": tool,
                        "role": role,
                        "status": "role_busy",
                        "limit": limit,
                    },
                )
                return {
                    "status": "role_busy",
                    "role": role,
                    "limit": limit,
                    "note": (
                        f"all {limit} concurrent slots for role '{role}' are busy and none "
                        f"freed within {slot_wait:.0f}s; dispatch a different role, wait and "
                        "retry, or finalize_task if blocked"
                    ),
                }

            try:
                await _notify_status(on_status, "dispatching_subagent", detail)
                effective_agent_worktree_path = agent_worktree_path
                if dispatch_start_lock is None:
                    if pre_dispatch_check is not None:
                        pre_dispatch_result = await pre_dispatch_check()
                        if pre_dispatch_result is not None:
                            if "result" in pre_dispatch_result:
                                return pre_dispatch_result["result"]
                            effective_agent_worktree_path = pre_dispatch_result.get(
                                "agent_worktree_path",
                                effective_agent_worktree_path,
                            )
                    task_id, node_id = await task_dispatcher_module.dispatch_role(  # noqa: RUF059
                        issue=issue,
                        role=role,
                        prompt_override=prompt_override,
                        store=store,
                        task_dispatcher_fn=task_dispatcher_fn,
                        event_bus=event_bus,
                        prev_node_key=prev_node_key,
                        agent_worktree_path=effective_agent_worktree_path,
                        batch_key=batch_key,
                        register_completion=True,
                    )
                else:
                    async with dispatch_start_lock:
                        if pre_dispatch_check is not None:
                            pre_dispatch_result = await pre_dispatch_check()
                            if pre_dispatch_result is not None:
                                if "result" in pre_dispatch_result:
                                    return pre_dispatch_result["result"]
                                effective_agent_worktree_path = pre_dispatch_result.get(
                                    "agent_worktree_path",
                                    effective_agent_worktree_path,
                                )
                        task_id, node_id = await task_dispatcher_module.dispatch_role(  # noqa: RUF059
                            issue=issue,
                            role=role,
                            prompt_override=prompt_override,
                            store=store,
                            task_dispatcher_fn=task_dispatcher_fn,
                            event_bus=event_bus,
                            prev_node_key=prev_node_key,
                            agent_worktree_path=effective_agent_worktree_path,
                            batch_key=batch_key,
                            register_completion=True,
                        )
                # register_completion=True makes dispatch_role register the task
                # in the completion registry BEFORE launching its runner, so an
                # instantly-completing task (e.g. executor_failed_to_start
                # fail-fast) can't signal before we're listening. This closes the
                # signal-before-register race that stalled dispatch until
                # hard_timeout (and leaked agent worktrees in dispatch_batch).
            except ValueError as exc:
                return {"error": str(exc), "role": role}
            except Exception as exc:
                await _emit(
                    event_bus,
                    "conductor_tool",
                    {
                        "tool": tool,
                        "role": role,
                        "status": "dispatch_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                return {"error": f"{type(exc).__name__}: {exc}", "role": role}

            registry = TaskCompletionRegistry.get()
            # Idempotent safety net: dispatch_role already registered task_id
            # (register_completion=True). Re-registering never clobbers a set event.
            registry.register(task_id)
            await _notify_status(on_status, "awaiting_subagent", detail)

            await _emit(
                event_bus,
                "conductor_tool",
                {
                    "tool": tool,
                    "role": role,
                    "task_id": task_id,
                    "status": "dispatched",
                },
            )

            # Activity-aware wait: a slow-but-progressing subagent (e.g. a thorough
            # gpt-5.5 QA pass that streams for >900s) must NOT be abandoned and
            # redispatched — that discards its work. Keep waiting while it shows
            # recent activity; only give up on a genuine stall or the hard ceiling.
            def _activity_age(tid: str) -> float | None:
                last = task_activity.last_activity.get(tid)
                return None if last is None else (datetime.now() - last).total_seconds()

            idle_timeout = timeouts.subagent_idle_s()
            hard_timeout = timeouts.subagent_max_s()
            try:
                result = await registry.wait_for_active(
                    task_id,
                    idle_timeout=idle_timeout,
                    hard_timeout=hard_timeout,
                    activity_age=_activity_age,
                )
            except TimeoutError:
                timeout_error = (
                    f"subagent timed out (idle >{idle_timeout:.0f}s or total >{hard_timeout:.0f}s)"
                )
                node_key = await _load_workflow_node_key(issue.id, node_id, fallback=role)
                try:
                    from app.bootstrap import get_codex_process_manager

                    mgr = get_codex_process_manager()
                    terminated = mgr.terminate_task(task_id)
                    if asyncio.iscoroutine(terminated):
                        await terminated
                except Exception:
                    pass
                try:
                    task = await store.load_codex_task(task_id)
                    if task is not None and not is_task_terminal_status(task.status):
                        task.status = "failed"
                        task.result = timeout_error
                        task.updated_at = datetime.now()
                        await store.save_codex_task(task)
                        from app.application.task_status_events import build_task_status_event

                        await _emit(
                            event_bus,
                            "task_status",
                            build_task_status_event(task, "failed", result=task.result),
                        )
                except Exception:
                    pass
                try:
                    await store.update_workflow_node(
                        node_id,
                        status="failed",
                        task_id=task_id,
                        completed_at=datetime.now(),
                    )
                    await _emit(
                        event_bus,
                        "workflow_node_updated",
                        {
                            "issue_id": issue.id,
                            "session_id": issue.session_id,
                            "node_id": node_id,
                            "node_key": node_key,
                            "status": "failed",
                            "task_id": task_id,
                            "batch_key": batch_key,
                        },
                    )
                except Exception:
                    pass
                return {
                    "error": timeout_error,
                    "task_id": task_id,
                    "role": role,
                }

            return result or {"task_id": task_id, "role": role, "status": "done"}

    async def dispatch_subagent(tool_input: dict[str, Any]) -> dict[str, Any]:
        if task_dispatcher_fn is None or not issue_id:
            # Fallback stub (project-level ad-hoc usage without issue context)
            payload = {
                "project_id": project_id,
                "node_key": tool_input.get("node_key"),
                "role": tool_input.get("role"),
                "prompt": tool_input.get("prompt"),
                "status": "queued",
                "note": "no issue context",
            }
            await _emit(event_bus, "conductor_tool", {"tool": "dispatch_subagent", **payload})
            return payload

        role = normalize_role(str(tool_input.get("role") or ""))
        prompt_override = tool_input.get("prompt") or None
        prev_node_key = tool_input.get("prev_node_key") or None

        issue = await store.load_codex_issue(issue_id)
        if issue is None:
            return {"error": f"Issue {issue_id} not found"}

        budget_blocked = await _check_budget_gate(issue, tool="dispatch_subagent")
        if budget_blocked is not None:
            return budget_blocked

        exhausted = await _check_redispatch_budget(role, tool="dispatch_subagent")
        if exhausted is not None:
            return exhausted

        async def _pre_dispatch_check() -> dict[str, Any] | None:
            budget_blocked = await _check_budget_gate(issue, tool="dispatch_subagent")
            if budget_blocked is not None:
                return {"result": budget_blocked}
            exhausted = await _check_redispatch_budget(role, tool="dispatch_subagent")
            if exhausted is not None:
                return {"result": exhausted}
            return None

        # Serial path: no per-agent worktree, the task runs in the shared issue
        # worktree exactly as before.
        return await _run_single_dispatch(
            issue=issue,
            role=role,
            prompt_override=prompt_override,
            prev_node_key=prev_node_key,
            agent_worktree_path=None,
            tool="dispatch_subagent",
            dispatch_start_lock=_dispatch_start_lock_for_issue(issue.id),
            pre_dispatch_check=_pre_dispatch_check,
        )

    async def dispatch_batch(tool_input: dict[str, Any]) -> dict[str, Any]:
        """Fan out N INDEPENDENT subagents concurrently, each in its own isolated
        worktree. Partial-join semantics: a single agent failing/timing out does
        not abort the batch; its error is collected as a `failed` result item."""
        if task_dispatcher_fn is None or not issue_id:
            payload = {
                "project_id": project_id,
                "status": "queued",
                "note": "no issue context",
                "agents": tool_input.get("agents"),
            }
            await _emit(event_bus, "conductor_tool", {"tool": "dispatch_batch", **payload})
            return payload

        from app.application import timeouts

        raw_agents = tool_input.get("agents")
        if not isinstance(raw_agents, list) or not raw_agents:
            return {"error": "dispatch_batch requires a non-empty 'agents' list"}

        issue = await store.load_codex_issue(issue_id)
        if issue is None:
            return {"error": f"Issue {issue_id} not found"}

        budget_status, budget_failure = await _compute_budget_status(
            issue,
            tool="dispatch_batch",
        )
        if budget_failure is not None:
            return budget_failure
        if budget_status is not None:
            budget_blocked = await _budget_exceeded_result(
                issue,
                budget_status,
                tool="dispatch_batch",
            )
            if budget_blocked is not None:
                return budget_blocked

        project = await store.load_project(issue.project_id)
        if project is None:
            return {"error": f"Project {issue.project_id} not found"}

        wm = _resolve_worktree_manager()

        # One shared batch_key tags every node this dispatch_batch call creates, so
        # the WorkflowGraph / mesh UI can render the concurrent agents in a single
        # parallel swimlane (vs. the serial chain). Short, sortable, unique enough.
        batch_key = f"batch-{uuid4().hex[:8]}"

        # Normalize specs and assign a unique agent_key per spec (used for the
        # user-facing result key). Same role twice in one batch gets distinct keys
        # (role, role-2, …). The worktree key also includes batch_key so concurrent
        # dispatch_batch calls for the same issue/role never share an agent branch
        # or directory.
        specs: list[dict[str, Any]] = []
        seen_keys: dict[str, int] = {}
        for idx, raw in enumerate(raw_agents):
            if not isinstance(raw, dict):
                return {"error": f"agents[{idx}] must be an object with at least a 'role'"}
            role = normalize_role(str(raw.get("role") or "").strip())
            if not role:
                return {"error": f"agents[{idx}] is missing 'role'"}
            base_key = _sanitize_agent_key(role)
            n = seen_keys.get(base_key, 0)
            seen_keys[base_key] = n + 1
            agent_key = base_key if n == 0 else f"{base_key}-{n + 1}"
            specs.append(
                {
                    "agent_key": agent_key,
                    "worktree_key": f"{agent_key}-{batch_key}",
                    "role": role,
                    "prompt": raw.get("prompt") or None,
                    "prev_node_key": raw.get("prev_node_key") or None,
                }
            )

        batch_exhausted = await _check_batch_redispatch_budget(specs, tool="dispatch_batch")
        if batch_exhausted is not None:
            return batch_exhausted

        # Budget-aware concurrency (PR3): the configured fan-out cap is the upper
        # bound, but a tight remaining budget dynamically downscales the EFFECTIVE
        # concurrency (concurrency = cost multiplier). Unlimited budget (or a
        # comfortable one) leaves the cap untouched; over budget squeezes to 1.
        # This can only ever REDUCE parallelism, never raise it. Best-effort: a
        # budget-status failure falls back to the plain configured cap.
        configured_cap = timeouts.max_parallel_dispatch_per_batch()
        cap = configured_cap
        budget_status, budget_failure = await _compute_budget_status(
            issue,
            tool="dispatch_batch",
        )
        if budget_failure is not None:
            return budget_failure
        if budget_status is not None:
            cap = timeouts.budget_supported_concurrency(
                budget_status.remaining_usd,
                configured_cap,
                soft_warn=budget_status.soft_warn,
                over_budget=budget_status.over_budget,
            )
        sem = asyncio.Semaphore(cap)
        dispatch_gate_lock = _dispatch_start_lock_for_issue(issue.id)

        # Upstream-visibility fix (PR1 check): isolated agent worktrees fork from
        # the issue branch and only see what's committed there. Flush any
        # uncommitted upstream artifacts (PM / architect) onto the issue branch
        # BEFORE creating per-agent worktrees, else fan-out agents start stale.
        try:
            flushed = await wm.commit_issue_worktree(issue)
            if flushed:
                await _emit(
                    event_bus,
                    "conductor_tool",
                    {
                        "tool": "dispatch_batch",
                        "status": "upstream_flushed",
                        "sha": flushed,
                    },
                )
        except Exception:  # noqa: BLE001, RUF100
            # Best-effort: a flush failure shouldn't block fan-out, but agents
            # may not see the freshest uncommitted upstream state.
            pass

        await _emit(
            event_bus,
            "conductor_tool",
            {
                "tool": "dispatch_batch",
                "status": "batch_started",
                "batch_key": batch_key,
                "agent_count": len(specs),
                "concurrency_cap": cap,
                "configured_cap": configured_cap,
                "roles": [s["role"] for s in specs],
            },
        )

        async def _run_one(spec: dict[str, Any]) -> dict[str, Any]:
            agent_key = spec["agent_key"]
            worktree_key = spec["worktree_key"]
            role = spec["role"]
            async with sem:
                worktree_path: str | None = None
                agent_branch: str | None = None
                cleanup_on_exit = False
                try:
                    async def _pre_dispatch_check() -> dict[str, Any] | None:
                        nonlocal agent_branch, worktree_path
                        # Budget gate after acquiring the batch slot, before
                        # creating any task/node/worktree. The batch-level
                        # preflight can be stale after earlier agents reserve
                        # or spend budget.
                        budget_blocked = await _check_budget_gate(issue, tool="dispatch_batch")
                        if budget_blocked is not None:
                            return {
                                "result": {
                                    "agent_key": agent_key,
                                    "role": role,
                                    **budget_blocked,
                                }
                            }

                        # Dispatch-count check per role, mirroring dispatch_subagent.
                        exhausted = await _check_redispatch_budget(role, tool="dispatch_batch")
                        if exhausted is not None:
                            return {"result": {"agent_key": agent_key, **exhausted}}

                        agent_branch, worktree_path, _ = await wm.prepare_agent_worktree(
                            project, issue, worktree_key
                        )
                        return {"agent_worktree_path": worktree_path}

                    result = await _run_single_dispatch(
                        issue=issue,
                        role=role,
                        prompt_override=spec["prompt"],
                        prev_node_key=spec["prev_node_key"],
                        agent_worktree_path=None,
                        tool="dispatch_batch",
                        batch_key=batch_key,
                        dispatch_start_lock=dispatch_gate_lock,
                        pre_dispatch_check=_pre_dispatch_check,
                    )
                    # PR3 will merge these per-agent branches back into the issue
                    # branch, so on success we KEEP the worktree (its commits are
                    # the agent's output). Failed/never-dispatched agents have no
                    # mergeable output → clean their worktree now to avoid leaks.
                    status = result.get("status")
                    if (
                        "error" in result or not _is_successful_subagent_status(status)
                    ) and (agent_branch or worktree_path):
                        cleanup_on_exit = True
                    return {
                        **result,
                        "agent_key": agent_key,
                        "role": role,
                        "branch": agent_branch,
                        "worktree_path": worktree_path,
                    }
                except asyncio.CancelledError:
                    if agent_branch or worktree_path:
                        cleanup_on_exit = True
                    raise
                except Exception as exc:  # noqa: BLE001, RUF100
                    cleanup_on_exit = True
                    return {
                        "agent_key": agent_key,
                        "role": role,
                        "branch": agent_branch,
                        "worktree_path": worktree_path,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                finally:
                    if cleanup_on_exit:
                        try:  # noqa: SIM105
                            await wm.cleanup_agent_worktree(project, issue, worktree_key)
                        except Exception:  # noqa: BLE001, RUF100
                            pass

        # return_exceptions=True → partial join: a crashing coroutine does not
        # propagate and kill its siblings (research §3 asyncio pitfall). _run_one
        # already converts in-band failures to result dicts, so this is a final
        # safety net for anything that escapes it.
        gathered = await asyncio.gather(*(_run_one(spec) for spec in specs), return_exceptions=True)

        results: list[dict[str, Any]] = []
        for spec, item in zip(specs, gathered):  # noqa: B905
            if isinstance(item, BaseException):
                results.append(
                    {
                        "agent_key": spec["agent_key"],
                        "role": spec["role"],
                        "error": f"{type(item).__name__}: {item}",
                    }
                )
            else:
                results.append(item)

        succeeded = [
            r
            for r in results
            if "error" not in r and _is_successful_subagent_status(r.get("status"))
        ]
        failed = [r for r in results if r not in succeeded]

        await _emit(
            event_bus,
            "conductor_tool",
            {
                "tool": "dispatch_batch",
                "status": "batch_complete",
                "succeeded": len(succeeded),
                "failed": len(failed),
            },
        )

        # Join / reconcile (PR3): sequentially squash-merge the successful agents'
        # branches back into the issue branch. Lineage is passed in-memory (branch
        # + worktree_path captured per result), so nothing extra is persisted.
        # Only agents that actually produced a branch are merge candidates.
        merge_candidates = [
            {
                "agent_key": r["agent_key"],
                "role": r.get("role"),
                "branch": r.get("branch"),
                "worktree_path": r.get("worktree_path"),
            }
            for r in succeeded
            if r.get("branch")
        ]

        merge_summary: dict[str, Any] = {"merged": [], "conflict": None, "skipped": [], "noop": []}
        if merge_candidates:
            await _emit(
                event_bus,
                "conductor_tool",
                {
                    "tool": "dispatch_batch",
                    "status": "merge_started",
                    "candidate_count": len(merge_candidates),
                },
            )
            try:
                merge_summary = await wm.merge_agent_worktrees(project, issue, merge_candidates)
            except Exception as exc:  # noqa: BLE001, RUF100
                merge_summary = {
                    "merged": [],
                    "conflict": None,
                    "skipped": [],
                    "noop": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            await _emit(
                event_bus,
                "conductor_tool",
                {
                    "tool": "dispatch_batch",
                    "status": "merge_complete",
                    "merged": len(merge_summary.get("merged") or []),
                    "conflict": bool(merge_summary.get("conflict")),
                    "skipped": len(merge_summary.get("skipped") or []),
                    "noop": len(merge_summary.get("noop") or []),
                },
            )

        conflict = merge_summary.get("conflict")
        merge_status = (
            "error"
            if merge_summary.get("error")
            else ("conflict" if conflict else ("merged" if merge_summary.get("merged") else "noop"))
        )

        out: dict[str, Any] = {
            "status": "batch_complete",
            "agent_count": len(results),
            "succeeded_count": len(succeeded),
            "failed_count": len(failed),
            "results": results,
            "merge_status": merge_status,
            "merged": merge_summary.get("merged") or [],
            "skipped_merges": merge_summary.get("skipped") or [],
            "noop_merges": merge_summary.get("noop") or [],
        }
        if conflict:
            out["conflicts"] = [conflict]
            out["note"] = (
                "MERGE CONFLICT during join: agent "
                f"'{conflict.get('agent_key')}' (role '{conflict.get('role')}') "
                f"could not be merged into the issue branch — conflicting files: "
                f"{conflict.get('files')}. The conflicting agent's worktree is kept "
                "for reconcile. To resolve: dispatch a subagent (e.g. engineer) with "
                "a prompt that includes the conflicting files + diff and instructs it "
                "to reconcile the change, or use request_user_clarification to escalate. "
                "Agents merged before the conflict are already on the issue branch and "
                "were NOT rolled back."
            )
        elif merge_summary.get("error"):
            out["merge_error"] = merge_summary["error"]
            out["note"] = (
                "MERGE ERROR during join: successful agents finished, but their "
                "per-agent worktrees could not be reconciled into the issue branch. "
                "The merge error is preserved in 'merge_error'; inspect the kept "
                "agent worktrees before retrying or finalizing."
            )
        else:
            noop_note = ""
            if out["noop_merges"]:
                noop_keys = [n.get("agent_key") for n in out["noop_merges"]]
                noop_note = (
                    f" Agents with no changes to merge were treated as clean no-ops "
                    f"and cleaned up (not conflicts): {noop_keys}."
                )
            out["note"] = (
                "Partial join complete: successful agents were squash-merged into the "
                "issue branch in order; their per-agent worktrees were cleaned up. "
                "Failed agents (see 'error' on their result) produced no mergeable output."
                + noop_note
            )
        return out

    async def _load_workflow_node_key(
        issue_id: str,
        node_id: str,
        *,
        fallback: str,
    ) -> str:
        try:
            graph = await store.load_workflow_graph_for_issue(issue_id)
        except Exception:  # noqa: BLE001, RUF100
            return fallback
        for node in getattr(graph, "nodes", None) or []:
            if str(getattr(node, "id", "") or "") == node_id:
                return str(getattr(node, "node_key", "") or "") or fallback
        return fallback

    async def spawn_custom_subagent(tool_input: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "project_id": project_id,
            "role_key": tool_input.get("role_key"),
            "label": tool_input.get("label"),
            "prompt": tool_input.get("prompt"),
            "status": "registered",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "spawn_custom_subagent", **payload})
        return payload

    async def inject_context_into_node(tool_input: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "project_id": project_id,
            "node_key": tool_input.get("node_key"),
            "context": tool_input.get("context"),
            "status": "accepted",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "inject_context_into_node", **payload})
        return payload

    async def request_user_clarification(tool_input: dict[str, Any]) -> dict[str, Any]:
        await _notify_status(
            on_status,
            "awaiting_user_clarification",
            str(tool_input.get("question") or "").strip() or None,
        )
        payload = {
            "project_id": project_id,
            "question": tool_input.get("question"),
            "status": "waiting_for_user",
            "terminal_status": "needs_user",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "request_user_clarification", **payload})
        return payload

    async def finalize_task(tool_input: dict[str, Any]) -> dict[str, Any]:
        raw_status = normalize_task_status(tool_input.get("status") or "done")
        if raw_status in TASK_SUCCESS_STATUSES:
            status = "done"
        elif raw_status in TASK_FAILURE_STATUSES | {
            "blocked",
            "needs_user",
            "max_wall",
            "max_turns",
        }:
            status = raw_status
        else:
            status = "failed"
        answer = str(tool_input.get("answer") or tool_input.get("summary") or "")
        summary = str(tool_input.get("summary") or tool_input.get("answer") or "")
        if status == "done":
            blocked = await _check_finalize_success_gate()
            if blocked is not None:
                await _emit(
                    event_bus,
                    "conductor_tool",
                    {
                        "tool": "finalize_task",
                        "status": "finalize_rejected",
                        "requested_status": raw_status,
                        "reason": blocked.get("reason"),
                        "blocking_nodes": blocked.get("blocking_nodes"),
                    },
                )
                reason = str(blocked.get("reason") or "success gate rejected finalize_task")
                if answer:
                    answer = f"{answer}\n\n[finalize rejected] {reason}"
                else:
                    answer = reason
                if summary:
                    summary = f"{summary}\n\n[finalize rejected] {reason}"
                else:
                    summary = reason
                status = str(blocked.get("status") or "failed")
        return {
            "status": status,
            "answer": answer,
            "summary": summary,
        }

    tools: dict[str, ToolCallable] = {
        "retrieve_cold_memory": retrieve_cold_memory,
        "dispatch_subagent": dispatch_subagent,
        "dispatch_batch": dispatch_batch,
        "spawn_custom_subagent": spawn_custom_subagent,
        "inject_context_into_node": inject_context_into_node,
        "request_user_clarification": request_user_clarification,
        "finalize_task": finalize_task,
    }
    return ConductorToolRegistry(definitions=_tool_definitions(), tools=tools)


def _sanitize_agent_key(role: str) -> str:
    """Turn a role into a filesystem/branch-safe agent key for swarm worktrees."""
    key = re.sub(r"[^a-zA-Z0-9._-]+", "-", role.strip()).strip("-").lower()
    return key or "agent"


def _is_successful_subagent_status(status: Any) -> bool:
    return is_task_success_status(str(status or ""))


async def _emit(event_bus, event_type: str, payload: dict[str, Any]) -> None:
    if event_bus is None:
        return
    if hasattr(event_bus, "emit"):
        result = event_bus.emit(event_type, payload)
    elif hasattr(event_bus, "append"):
        result = event_bus.append({"type": event_type, **payload})
    else:
        return
    if hasattr(result, "__await__"):
        await result


async def _notify_status(
    callback: ToolStatusCallback | None, phase: str, detail: str | None
) -> None:
    if callback is None:
        return
    result = callback(phase, detail)
    if hasattr(result, "__await__"):
        await result


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        _tool(
            "retrieve_cold_memory",
            "Search ProjectConductor cold memory for relevant project history.",
            {
                "query": {"type": "string", "description": "Search query."},
                "top_k": {"type": "integer", "description": "Maximum memories to return."},
            },
            ["query"],
        ),
        _tool(
            "dispatch_subagent",
            "Dispatch a workflow sub-agent by role. Waits for completion and returns the result. Available roles: product_manager, architect, engineer, operations_engineer, qa. You can also use specialist role keys from the agent catalog.",
            {
                "role": {
                    "type": "string",
                    "description": "Role to dispatch: product_manager, architect, engineer, operations_engineer, qa, or a specialist role_key",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional focused instruction for this agent run",
                },
                "prev_node_key": {
                    "type": "string",
                    "description": "node_key of the previously dispatched node, for graph edge visualization",
                },
            },
            ["role"],
        ),
        _tool(
            "dispatch_batch",
            (
                "Fan out MULTIPLE INDEPENDENT sub-agents concurrently in a single "
                "decision and wait for the whole batch. Use this ONLY when the "
                "agents are truly independent (no agent needs another's output) — "
                "for example splitting unrelated parts of the work across several "
                "engineers. Each agent runs in its own isolated worktree so their "
                "file edits never clobber each other. If agents depend on each "
                "other, dispatch them sequentially with dispatch_subagent across "
                "turns instead. Returns one result per agent (success payload or "
                "an 'error'); a single agent failing does not abort the batch. "
                "After the agents finish, their changes are automatically "
                "squash-merged back into the issue branch in order. The return "
                "value has 'merge_status': 'merged' (all clean), 'noop' (nothing "
                "to merge), or 'conflict'. On 'conflict', a 'conflicts' list gives "
                "the conflicting agent, files, and diff — resolve it by dispatching "
                "a subagent to reconcile those files, or request_user_clarification."
            ),
            {
                "agents": {
                    "type": "array",
                    "description": "List of independent agents to run concurrently.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {
                                "type": "string",
                                "description": "Role to dispatch: product_manager, architect, engineer, operations_engineer, qa, or a specialist role_key",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "Optional focused instruction for this agent run",
                            },
                            "prev_node_key": {
                                "type": "string",
                                "description": "node_key of a previously dispatched node, for graph edge visualization",
                            },
                        },
                        "required": ["role"],
                    },
                },
            },
            ["agents"],
        ),
        _tool(
            "spawn_custom_subagent",
            "Register a custom specialist sub-agent for a project-specific task.",
            {
                "role_key": {"type": "string"},
                "label": {"type": "string"},
                "prompt": {"type": "string"},
            },
            ["role_key", "prompt"],
        ),
        _tool(
            "inject_context_into_node",
            "Inject conductor context into a pending workflow node.",
            {
                "node_key": {"type": "string"},
                "context": {"type": "string"},
            },
            ["node_key", "context"],
        ),
        _tool(
            "request_user_clarification",
            "Ask the user a blocking clarification question.",
            {"question": {"type": "string"}},
            ["question"],
        ),
        _tool(
            "finalize_task",
            "Finish the conductor task with a final answer.",
            {
                "answer": {"type": "string"},
                "summary": {"type": "string"},
                "status": {"type": "string"},
            },
            [],
        ),
    ]


def _tool(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
