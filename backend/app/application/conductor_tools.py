"""Tool registry for the ProjectConductor loop."""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from app.application.project_conductor import ProjectConductor


ToolCallable = Callable[[dict[str, Any]], Awaitable[Any]]
ToolStatusCallback = Callable[[str, str | None], Awaitable[None] | None]


def _max_dispatches_per_role() -> int:
    """GAP G: max times the Conductor may dispatch the same role for one issue
    before the tool returns `retries_exhausted`. Allows the initial run plus a
    few reworks (e.g. engineer after QA failure) without unbounded looping."""
    raw = os.getenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE")
    if not raw:
        return 4
    try:
        return max(1, int(raw))
    except ValueError:
        return 4


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

    async def _check_redispatch_budget(role: str, *, tool: str) -> dict[str, Any] | None:
        """GAP G: bound re-dispatch. Each dispatch of a role adds a graph node
        (role, role#1, role#2…); past the budget the Conductor is stuck in a
        rework loop. Returns a terminal `retries_exhausted` dict when exhausted,
        else None. Shared by dispatch_subagent and dispatch_batch."""
        if not role or not issue_id:
            return None
        try:
            graph = await store.load_workflow_graph_for_issue(issue_id)
        except Exception:  # noqa: BLE001
            graph = None
        if graph is None:
            return None
        same_role = sum(
            1 for n in (graph.nodes or [])
            if n.node_key == role or n.node_key.startswith(f"{role}#")
        )
        max_dispatches = _max_dispatches_per_role()
        if same_role < max_dispatches:
            return None
        await _emit(event_bus, "conductor_tool", {
            "tool": tool,
            "role": role,
            "status": "retries_exhausted",
            "dispatches": same_role,
        })
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

    async def _run_single_dispatch(
        *,
        issue,
        role: str,
        prompt_override: str | None,
        prev_node_key: str | None,
        agent_worktree_path: str | None,
        tool: str,
        batch_key: str | None = None,
    ) -> dict[str, Any]:
        """Run one subagent dispatch end-to-end: acquire a per-role concurrency
        slot, dispatch the role task, then activity-aware wait for completion.

        This is the single source of truth for the dispatch lifecycle, shared by
        both dispatch_subagent (serial path, agent_worktree_path=None → shared
        issue worktree) and dispatch_batch (parallel path, agent_worktree_path
        set → isolated per-agent worktree). Returns the subagent result dict or a
        structured status/error dict (role_busy / timeout / value error)."""
        from datetime import datetime
        from app.application import task_activity, timeouts
        from app.application.role_concurrency import RoleConcurrencyLimiter
        from app.application.task_completion_registry import TaskCompletionRegistry
        from app.application.task_dispatcher import dispatch_role

        detail = role or prev_node_key or "subagent"

        # GAP: enforce MAX_CONCURRENT_INSTANCES_PER_ROLE. Acquire a process-wide
        # slot for this role BEFORE dispatching, so we never create a task/node
        # we can't actually run within the cap. The slot is held for the whole
        # subagent run and released when wait_for_active returns or times out.
        # If every slot is busy past role_slot_wait_s, return a structured
        # `role_busy` so the Conductor re-plans instead of blocking forever.
        limiter = RoleConcurrencyLimiter.instance()
        slot_role = role or "subagent"
        slot_wait = timeouts.role_slot_wait_s()
        async with limiter.slot(slot_role, timeout=slot_wait) as acquired:
            if not acquired:
                limit = timeouts.max_concurrent_instances_per_role()
                await _emit(event_bus, "conductor_tool", {
                    "tool": tool,
                    "role": role,
                    "status": "role_busy",
                    "limit": limit,
                })
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
                task_id, node_id = await dispatch_role(
                    issue=issue,
                    role=role,
                    prompt_override=prompt_override,
                    store=store,
                    task_dispatcher_fn=task_dispatcher_fn,
                    event_bus=event_bus,
                    prev_node_key=prev_node_key,
                    agent_worktree_path=agent_worktree_path,
                    batch_key=batch_key,
                )
            except ValueError as exc:
                return {"error": str(exc), "role": role}

            registry = TaskCompletionRegistry.get()
            registry.register(task_id)
            await _notify_status(on_status, "awaiting_subagent", detail)

            await _emit(event_bus, "conductor_tool", {
                "tool": tool,
                "role": role,
                "task_id": task_id,
                "status": "dispatched",
            })

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
                return {
                    "error": (
                        f"subagent timed out (idle >{idle_timeout:.0f}s or total >{hard_timeout:.0f}s)"
                    ),
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

        role = str(tool_input.get("role") or "")
        prompt_override = tool_input.get("prompt") or None
        prev_node_key = tool_input.get("prev_node_key") or None

        issue = await store.load_codex_issue(issue_id)
        if issue is None:
            return {"error": f"Issue {issue_id} not found"}

        exhausted = await _check_redispatch_budget(role, tool="dispatch_subagent")
        if exhausted is not None:
            return exhausted

        # Serial path: no per-agent worktree, the task runs in the shared issue
        # worktree exactly as before.
        return await _run_single_dispatch(
            issue=issue,
            role=role,
            prompt_override=prompt_override,
            prev_node_key=prev_node_key,
            agent_worktree_path=None,
            tool="dispatch_subagent",
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

        project = await store.load_project(issue.project_id)
        if project is None:
            return {"error": f"Project {issue.project_id} not found"}

        wm = _resolve_worktree_manager()

        # Normalize specs and assign a unique agent_key per spec (used for the
        # per-agent worktree branch/path and for cleanup). Same role twice in one
        # batch gets distinct keys (role, role-2, …) so worktrees never collide.
        specs: list[dict[str, Any]] = []
        seen_keys: dict[str, int] = {}
        for idx, raw in enumerate(raw_agents):
            if not isinstance(raw, dict):
                return {"error": f"agents[{idx}] must be an object with at least a 'role'"}
            role = str(raw.get("role") or "").strip()
            if not role:
                return {"error": f"agents[{idx}] is missing 'role'"}
            base_key = _sanitize_agent_key(role)
            n = seen_keys.get(base_key, 0)
            seen_keys[base_key] = n + 1
            agent_key = base_key if n == 0 else f"{base_key}-{n + 1}"
            specs.append({
                "agent_key": agent_key,
                "role": role,
                "prompt": raw.get("prompt") or None,
                "prev_node_key": raw.get("prev_node_key") or None,
            })

        # Budget-aware concurrency (PR3): the configured fan-out cap is the upper
        # bound, but a tight remaining budget dynamically downscales the EFFECTIVE
        # concurrency (concurrency = cost multiplier). Unlimited budget (or a
        # comfortable one) leaves the cap untouched; over budget squeezes to 1.
        # This can only ever REDUCE parallelism, never raise it. Best-effort: a
        # budget-status failure falls back to the plain configured cap.
        configured_cap = timeouts.max_parallel_dispatch_per_batch()
        cap = configured_cap
        try:
            from app.application.budget_service import compute_issue_budget_status

            budget_status = await compute_issue_budget_status(store, issue)
            cap = timeouts.budget_supported_concurrency(
                budget_status.remaining_usd,
                configured_cap,
                over_budget=budget_status.over_budget,
            )
        except Exception:  # noqa: BLE001
            cap = configured_cap
        sem = asyncio.Semaphore(cap)

        # One shared batch_key tags every node this dispatch_batch call creates, so
        # the WorkflowGraph / mesh UI can render the concurrent agents in a single
        # parallel swimlane (vs. the serial chain). Short, sortable, unique enough.
        batch_key = f"batch-{uuid4().hex[:8]}"

        # Upstream-visibility fix (PR1 check): isolated agent worktrees fork from
        # the issue branch and only see what's committed there. Flush any
        # uncommitted upstream artifacts (PM / architect) onto the issue branch
        # BEFORE creating per-agent worktrees, else fan-out agents start stale.
        try:
            flushed = await wm.commit_issue_worktree(issue)
            if flushed:
                await _emit(event_bus, "conductor_tool", {
                    "tool": "dispatch_batch",
                    "status": "upstream_flushed",
                    "sha": flushed,
                })
        except Exception:  # noqa: BLE001
            # Best-effort: a flush failure shouldn't block fan-out, but agents
            # may not see the freshest uncommitted upstream state.
            pass

        await _emit(event_bus, "conductor_tool", {
            "tool": "dispatch_batch",
            "status": "batch_started",
            "batch_key": batch_key,
            "agent_count": len(specs),
            "concurrency_cap": cap,
            "configured_cap": configured_cap,
            "roles": [s["role"] for s in specs],
        })

        async def _run_one(spec: dict[str, Any]) -> dict[str, Any]:
            agent_key = spec["agent_key"]
            role = spec["role"]
            async with sem:
                # Budget check per role, mirroring dispatch_subagent.
                exhausted = await _check_redispatch_budget(role, tool="dispatch_batch")
                if exhausted is not None:
                    return {"agent_key": agent_key, **exhausted}

                worktree_path: str | None = None
                agent_branch: str | None = None
                cleanup_on_exit = False
                try:
                    agent_branch, worktree_path, _ = await wm.prepare_agent_worktree(
                        project, issue, agent_key
                    )
                    result = await _run_single_dispatch(
                        issue=issue,
                        role=role,
                        prompt_override=spec["prompt"],
                        prev_node_key=spec["prev_node_key"],
                        agent_worktree_path=worktree_path,
                        tool="dispatch_batch",
                        batch_key=batch_key,
                    )
                    # PR3 will merge these per-agent branches back into the issue
                    # branch, so on success we KEEP the worktree (its commits are
                    # the agent's output). Failed/never-dispatched agents have no
                    # mergeable output → clean their worktree now to avoid leaks.
                    status = result.get("status")
                    if "error" in result or status in {"role_busy", "retries_exhausted"}:
                        cleanup_on_exit = True
                    return {
                        "agent_key": agent_key,
                        "role": role,
                        "branch": agent_branch,
                        "worktree_path": worktree_path,
                        **result,
                    }
                except Exception as exc:  # noqa: BLE001
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
                        try:
                            await wm.cleanup_agent_worktree(project, issue, agent_key)
                        except Exception:  # noqa: BLE001
                            pass

        # return_exceptions=True → partial join: a crashing coroutine does not
        # propagate and kill its siblings (research §3 asyncio pitfall). _run_one
        # already converts in-band failures to result dicts, so this is a final
        # safety net for anything that escapes it.
        gathered = await asyncio.gather(
            *(_run_one(spec) for spec in specs), return_exceptions=True
        )

        results: list[dict[str, Any]] = []
        for spec, item in zip(specs, gathered):
            if isinstance(item, BaseException):
                results.append({
                    "agent_key": spec["agent_key"],
                    "role": spec["role"],
                    "error": f"{type(item).__name__}: {item}",
                })
            else:
                results.append(item)

        succeeded = [r for r in results if "error" not in r and r.get("status") not in {"role_busy", "retries_exhausted"}]
        failed = [r for r in results if r not in succeeded]

        await _emit(event_bus, "conductor_tool", {
            "tool": "dispatch_batch",
            "status": "batch_complete",
            "succeeded": len(succeeded),
            "failed": len(failed),
        })

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

        merge_summary: dict[str, Any] = {"merged": [], "conflict": None, "skipped": []}
        if merge_candidates:
            await _emit(event_bus, "conductor_tool", {
                "tool": "dispatch_batch",
                "status": "merge_started",
                "candidate_count": len(merge_candidates),
            })
            try:
                merge_summary = await wm.merge_agent_worktrees(project, issue, merge_candidates)
            except Exception as exc:  # noqa: BLE001
                merge_summary = {
                    "merged": [],
                    "conflict": None,
                    "skipped": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            await _emit(event_bus, "conductor_tool", {
                "tool": "dispatch_batch",
                "status": "merge_complete",
                "merged": len(merge_summary.get("merged") or []),
                "conflict": bool(merge_summary.get("conflict")),
                "skipped": len(merge_summary.get("skipped") or []),
            })

        conflict = merge_summary.get("conflict")
        merge_status = "conflict" if conflict else ("merged" if merge_summary.get("merged") else "noop")

        out: dict[str, Any] = {
            "status": "batch_complete",
            "agent_count": len(results),
            "succeeded_count": len(succeeded),
            "failed_count": len(failed),
            "results": results,
            "merge_status": merge_status,
            "merged": merge_summary.get("merged") or [],
            "skipped_merges": merge_summary.get("skipped") or [],
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
        else:
            out["note"] = (
                "Partial join complete: successful agents were squash-merged into the "
                "issue branch in order; their per-agent worktrees were cleaned up. "
                "Failed agents (see 'error' on their result) produced no mergeable output."
            )
        return out

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
        await _notify_status(on_status, "awaiting_user_clarification", str(tool_input.get("question") or "").strip() or None)
        payload = {
            "project_id": project_id,
            "question": tool_input.get("question"),
            "status": "waiting_for_user",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "request_user_clarification", **payload})
        return payload

    async def finalize_task(tool_input: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": str(tool_input.get("status") or "done"),
            "answer": str(tool_input.get("answer") or tool_input.get("summary") or ""),
            "summary": str(tool_input.get("summary") or tool_input.get("answer") or ""),
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


async def _notify_status(callback: ToolStatusCallback | None, phase: str, detail: str | None) -> None:
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
            "Dispatch a workflow sub-agent by role. Waits for completion and returns the result. Available roles: product_manager, architect, engineer, qa. You can also use specialist role keys from the agent catalog.",
            {
                "role": {"type": "string", "description": "Role to dispatch: product_manager, architect, engineer, qa, or a specialist role_key"},
                "prompt": {"type": "string", "description": "Optional focused instruction for this agent run"},
                "prev_node_key": {"type": "string", "description": "node_key of the previously dispatched node, for graph edge visualization"},
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
                            "role": {"type": "string", "description": "Role to dispatch: product_manager, architect, engineer, qa, or a specialist role_key"},
                            "prompt": {"type": "string", "description": "Optional focused instruction for this agent run"},
                            "prev_node_key": {"type": "string", "description": "node_key of a previously dispatched node, for graph edge visualization"},
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


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
