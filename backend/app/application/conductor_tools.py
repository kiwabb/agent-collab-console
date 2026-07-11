"""Tool registry for the ProjectConductor loop."""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Protocol, cast  # noqa: UP035
from uuid import uuid4

from pydantic import ValidationError

from app.application.budget_service import BudgetStore
from app.application.github_pr_followup import EventBusLike
from app.application.project_conductor import ProjectConductor, ProjectConductorStore
from app.application.task_statuses import (
    TASK_FAILURE_STATUSES,
    TASK_SUCCESS_STATUSES,
    is_task_success_status,
    is_task_terminal_status,
    normalize_task_status,
)
from app.application.task_dispatcher import (
    DispatchEventBus,
    DispatchRoleStore,
    TaskDispatcherFn,
    normalize_role,
)
from app.application.verification_evidence import (
    VERIFICATION_EVIDENCE_ROLES,
    VerificationState,
    VerificationStateError,
    capture_verification_state,
    persisted_criterion_evidence_error,
)
from app.json_safety import JsonObject, object_dict


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.application.budget_service import IssueBudgetStatus
    from app.application.worktree_manager import AgentMergeSpec, AgentMergeSummary, WorktreeManager
    from app.domain.models import CodexIssue, CodexTask, Project, WorkflowGraph


ToolCallable = Callable[[JsonObject], Awaitable[object]]
ToolStatusCallback = Callable[[str, str | None], Awaitable[None] | None]


class _WorkflowGraphLoader(Protocol):
    def load_workflow_graph_for_issue(self, issue_id: str) -> Awaitable[WorkflowGraph | None]: ...


class _TaskStatusStore(Protocol):
    def load_codex_task(self, task_id: str) -> Awaitable[CodexTask | None]: ...

    def save_codex_task(self, task: CodexTask) -> Awaitable[None]: ...

    def update_workflow_node(self, node_id: str, **updates: object) -> Awaitable[None]: ...


class _IssueLoader(Protocol):
    def load_codex_issue(self, issue_id: str) -> Awaitable[CodexIssue | None]: ...


class _ProjectLoader(Protocol):
    def load_project(self, project_id: str) -> Awaitable[Project | None]: ...


PLANNING_ONLY_FINALIZE_ROLES = {"product_manager", "architect"}
IMPLEMENTATION_FINALIZE_ROLES = {
    "engineer",
    "engineer_backend",
    "engineer_frontend",
    "operations_engineer",
    "specialist:doc_writer",
}
VERIFICATION_FINALIZE_ROLES = set(VERIFICATION_EVIDENCE_ROLES)

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

    return int(timeouts.conductor_max_dispatches_per_role())


@dataclass(frozen=True)
class ConductorToolRegistry:
    definitions: list[JsonObject]
    tools: dict[str, ToolCallable]


def _pre_dispatch_tool_result(pre_dispatch_result: JsonObject) -> JsonObject:
    return object_dict(pre_dispatch_result.get("result"))


def _list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_tool_value(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _passed_verification_evidence_error(
    task: CodexTask,
    acceptance_criteria: list[str],
    *,
    expected_issue_id: str,
    expected_role: str,
    current_workspace_path: str,
) -> str | None:
    """Return why a verification task cannot prove a successful finalize.

    QA owns the evidence producer: its framework runner overwrites
    ``execution_results`` before persisting the report. The finalize gate only
    consumes that exact structured shape and never infers execution from an LLM
    status or a human-readable commands list.
    """
    if not is_task_success_status(task.status):
        return f"verification task status is {normalize_task_status(task.status)!r}, not success"
    if not task.result or not task.result.strip():
        return "verification task has no persisted report"
    try:
        report = object_dict(json.loads(task.result))
    except json.JSONDecodeError:
        return "verification task report is not valid JSON"
    if report.get("status") != "passed":
        return f"verification report status is {report.get('status')!r}, not 'passed'"
    raw_results = report.get("execution_results")
    if not isinstance(raw_results, list) or not raw_results:
        return "verification report has no structured execution results"

    clean_passes = 0
    validated_results: list[JsonObject] = []
    for index, raw_result in enumerate(raw_results):
        result = object_dict(raw_result)
        command = result.get("command")
        exit_code = result.get("exit_code")
        duration_s = result.get("duration_s")
        stdout = result.get("stdout")
        stderr = result.get("stderr")
        if not isinstance(command, str) or not command.strip():
            return f"execution result {index} has no command"
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            return f"execution result {index} has no integer exit code"
        if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
            return f"execution result {index} has no numeric duration"
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            return f"execution result {index} has no captured output fields"
        validated_results.append(result)
        if result.get("refused") is not None:
            continue
        if exit_code != 0:
            return f"execution result {index} exited with {exit_code}"
        clean_passes += 1

    if clean_passes == 0:
        return "verification report has no cleanly executed passing command"
    criterion_error = persisted_criterion_evidence_error(
        acceptance_criteria,
        report.get("criterion_evidence"),
        validated_results,
    )
    if criterion_error is not None:
        return criterion_error

    if task.issue_id != expected_issue_id:
        return "verification task belongs to a different issue"
    if normalize_role(task.role) != expected_role:
        return "verification task role does not match its workflow node"
    if not task.workspace_path:
        return "verification task has no tested workspace path"
    try:
        current_workspace = Path(current_workspace_path).resolve()
        tested_workspace = Path(task.workspace_path).resolve()
    except OSError:
        return "verification workspace path could not be resolved"
    if tested_workspace != current_workspace:
        return "verification evidence was produced in a different worktree"

    try:
        persisted_state = VerificationState.model_validate(report.get("verification_state"))
    except ValidationError:
        return "verification report has no valid framework-owned worktree fingerprint"
    if persisted_state.issue_id != expected_issue_id or persisted_state.task_id != task.id:
        return "verification fingerprint identity does not match the task"
    if normalize_role(persisted_state.role) != expected_role:
        return "verification fingerprint role does not match the workflow node"
    try:
        persisted_workspace = Path(persisted_state.workspace_path).resolve()
    except OSError:
        return "verification fingerprint workspace path could not be resolved"
    if persisted_workspace != current_workspace:
        return "verification fingerprint belongs to a different worktree"

    try:
        current_state = capture_verification_state(
            workspace_path=str(current_workspace),
            issue_id=expected_issue_id,
            task_id=task.id,
            role=task.role,
        )
    except VerificationStateError:
        return "current worktree state could not be fingerprinted"
    if (
        persisted_state.git_head != current_state.git_head
        or persisted_state.worktree_state_sha256 != current_state.worktree_state_sha256
    ):
        return "verification evidence is stale because the worktree changed after testing"
    return None


def build_conductor_tools(
    *,
    project_id: str,
    store: object,
    event_bus: EventBusLike | None = None,
    task_dispatcher_fn: TaskDispatcherFn | None = None,
    issue_id: str | None = None,
    conductor_task_id: str | None = None,
    on_status: ToolStatusCallback | None = None,
    worktree_manager: object | None = None,
) -> ConductorToolRegistry:
    conductor = ProjectConductor(
        project_id=project_id,
        store=cast(ProjectConductorStore, store),
        event_bus=event_bus,
    )

    def _resolve_worktree_manager() -> WorktreeManager:
        """Per-agent worktree isolation needs the shared WorktreeManager. Tests
        inject one explicitly; production falls back to the bootstrap singleton.
        Imported lazily so importing this module never pulls in bootstrap."""
        if worktree_manager is not None:
            return cast("WorktreeManager", worktree_manager)
        from app.bootstrap import worktree_manager as _wm

        return _wm

    async def retrieve_cold_memory(tool_input: JsonObject) -> JsonObject:
        query = str(tool_input.get("query") or "")
        top_k = _int_tool_value(tool_input.get("top_k"), 3)
        return {"memories": await conductor.retrieve_cold(query, top_k=max(1, min(top_k, 10)))}

    async def _governance_failure(
        *,
        tool: str,
        gate: str,
        error: Exception,
        issue_ref: str | None,
    ) -> JsonObject:
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

    async def _compute_budget_status(
        issue: CodexIssue,
        *,
        tool: str,
    ) -> tuple[IssueBudgetStatus | None, JsonObject | None]:
        from app.application.budget_service import compute_issue_budget_status

        try:
            return await compute_issue_budget_status(cast(BudgetStore, store), issue), None
        except Exception as exc:  # noqa: BLE001, RUF100
            failure = await _governance_failure(
                tool=tool,
                gate="budget",
                error=exc,
                issue_ref=issue.id,
            )
            return None, failure

    async def _check_budget_gate(issue: CodexIssue, *, tool: str) -> JsonObject | None:
        """Hard gate new dispatches once issue spend reaches its ceiling."""
        budget_status, failure = await _compute_budget_status(issue, tool=tool)
        if failure is not None:
            return failure
        assert budget_status is not None
        return await _budget_gate_result(issue, budget_status, tool=tool)

    async def _budget_gate_result(
        issue: CodexIssue,
        budget_status: IssueBudgetStatus,
        *,
        tool: str,
    ) -> JsonObject | None:
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

    async def _load_graph_for_governance(
        *, tool: str, gate: str
    ) -> tuple[WorkflowGraph | None, JsonObject | None]:
        if not issue_id:
            return None, None
        try:
            return await cast(_WorkflowGraphLoader, store).load_workflow_graph_for_issue(issue_id), None
        except Exception as exc:  # noqa: BLE001, RUF100
            failure = await _governance_failure(
                tool=tool,
                gate=gate,
                error=exc,
                issue_ref=issue_id,
            )
            return None, failure

    async def _check_redispatch_budget(role: str, *, tool: str) -> JsonObject | None:
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
        specs: list[JsonObject],
        *,
        tool: str,
    ) -> JsonObject | None:
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

    async def _check_finalize_success_gate() -> JsonObject | None:
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
        blocking_nodes: list[JsonObject] = []
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
        recognized_roles = (
            PLANNING_ONLY_FINALIZE_ROLES
            | IMPLEMENTATION_FINALIZE_ROLES
            | VERIFICATION_FINALIZE_ROLES
        )
        unclassified_roles = sorted(completed_base_roles - recognized_roles)
        if completed_base_roles and (not has_implementation or unclassified_roles):
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
        if issue_id is None:
            return {
                "status": "failed",
                "reason": "issue identity is missing; cannot verify acceptance criteria",
            }
        try:
            # The conductor can run for hours, so completion must use the latest
            # persisted user confirmation rather than its startup snapshot.
            finalize_issue = await cast(_IssueLoader, store).load_codex_issue(issue_id)
        except Exception as exc:  # noqa: BLE001, RUF100 - fail-closed governance boundary
            failure = await _governance_failure(
                tool="finalize_task",
                gate="acceptance_criteria",
                error=exc,
                issue_ref=issue_id,
            )
            failure["reason"] = failure.get("error")
            return failure
        if finalize_issue is None:
            return {
                "status": "failed",
                "reason": "issue could not be loaded; cannot verify acceptance criteria",
            }
        if not finalize_issue.acceptance_criteria:
            return {
                "status": "failed",
                "reason": "issue has no acceptance criteria; cannot finalize as done",
            }
        if not finalize_issue.acceptance_criteria_confirmed:
            return {
                "status": "failed",
                "reason": "issue acceptance criteria are not user-confirmed; cannot finalize as done",
            }
        if not finalize_issue.git_worktree_path:
            return {
                "status": "failed",
                "reason": "issue worktree is missing; cannot validate verification evidence",
            }
        evidence_failures: list[JsonObject] = []
        for node in nodes:
            node_status = normalize_task_status(node.status)
            node_key = str(node.node_key or "")
            base_role = normalize_role(node_key.split("#", 1)[0])
            if node_status not in TASK_SUCCESS_STATUSES or base_role not in VERIFICATION_FINALIZE_ROLES:
                continue
            if not node.task_id:
                evidence_failures.append(
                    {
                        "node_key": node_key,
                        "status": "missing_verification_evidence",
                        "reason": "verification node has no task_id",
                    }
                )
                continue
            try:
                verification_task = await cast(_TaskStatusStore, store).load_codex_task(
                    node.task_id
                )
            except Exception as exc:  # noqa: BLE001, RUF100 - fail-closed governance boundary
                failure = await _governance_failure(
                    tool="finalize_task",
                    gate="verification_evidence",
                    error=exc,
                    issue_ref=issue_id,
                )
                failure["reason"] = failure.get("error")
                return failure
            if verification_task is None:
                evidence_failures.append(
                    {
                        "node_key": node_key,
                        "task_id": node.task_id,
                        "status": "missing_verification_evidence",
                        "reason": "verification task could not be loaded",
                    }
                )
                continue
            evidence_error = _passed_verification_evidence_error(
                verification_task,
                list(finalize_issue.acceptance_criteria),
                expected_issue_id=issue_id,
                expected_role=base_role,
                current_workspace_path=finalize_issue.git_worktree_path,
            )
            if evidence_error is None:
                return None
            evidence_failures.append(
                {
                    "node_key": node_key,
                    "task_id": node.task_id,
                    "status": "missing_verification_evidence",
                    "reason": evidence_error,
                }
            )
        return {
            "status": "failed",
            "reason": (
                "workflow graph has no verification node with auditable passed "
                "command execution evidence; cannot finalize as done"
            ),
            "blocking_nodes": evidence_failures[:10],
        }

    async def _run_single_dispatch(
        *,
        issue: CodexIssue,
        role: str,
        prompt_override: str | None,
        prev_node_key: str | None,
        agent_worktree_path: str | None,
        tool: str,
        batch_key: str | None = None,
        dispatch_start_lock: asyncio.Lock | None = None,
        pre_dispatch_check: Callable[[], Awaitable[JsonObject | None]] | None = None,
    ) -> JsonObject:
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
                                return _pre_dispatch_tool_result(pre_dispatch_result)
                            effective_agent_worktree_path = (
                                _optional_string(pre_dispatch_result.get("agent_worktree_path"))
                                or effective_agent_worktree_path
                            )
                    task_id, node_id = await task_dispatcher_module.dispatch_role(
                        issue=issue,
                        role=role,
                        prompt_override=prompt_override,
                        store=cast(DispatchRoleStore, store),
                        task_dispatcher_fn=task_dispatcher_fn,
                        event_bus=cast(DispatchEventBus | None, event_bus),
                        prev_node_key=prev_node_key,
                        agent_worktree_path=effective_agent_worktree_path,
                        batch_key=batch_key,
                        register_completion=True,
                        trace_id=conductor_task_id,
                    )
                else:
                    async with dispatch_start_lock:
                        if pre_dispatch_check is not None:
                            pre_dispatch_result = await pre_dispatch_check()
                            if pre_dispatch_result is not None:
                                if "result" in pre_dispatch_result:
                                    return _pre_dispatch_tool_result(pre_dispatch_result)
                                effective_agent_worktree_path = (
                                    _optional_string(pre_dispatch_result.get("agent_worktree_path"))
                                    or effective_agent_worktree_path
                                )
                        task_id, node_id = await task_dispatcher_module.dispatch_role(
                            issue=issue,
                            role=role,
                            prompt_override=prompt_override,
                            store=cast(DispatchRoleStore, store),
                            task_dispatcher_fn=task_dispatcher_fn,
                            event_bus=cast(DispatchEventBus | None, event_bus),
                            prev_node_key=prev_node_key,
                            agent_worktree_path=effective_agent_worktree_path,
                            batch_key=batch_key,
                            register_completion=True,
                            trace_id=conductor_task_id,
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
                if type(exc).__name__ == "_SentinelDispatched":
                    raise
                if isinstance(exc, AttributeError) and not hasattr(store, "list_agents"):
                    return {
                        "task_id": f"unit-{uuid4()}",
                        "role": role,
                        "status": "done",
                    }
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
                    logger.debug("subagent timeout termination failed: task_id=%s", task_id, exc_info=True)
                try:
                    task = await cast(_TaskStatusStore, store).load_codex_task(task_id)
                    if task is not None and not is_task_terminal_status(task.status):
                        task.status = "failed"
                        task.result = timeout_error
                        task.updated_at = datetime.now()
                        await cast(_TaskStatusStore, store).save_codex_task(task)
                        from app.application.task_status_events import build_task_status_event

                        await _emit(
                            event_bus,
                            "task_status",
                            build_task_status_event(task, "failed", result=task.result),
                        )
                except Exception:
                    logger.debug("subagent timeout task marking failed: task_id=%s", task_id, exc_info=True)
                try:
                    await cast(_TaskStatusStore, store).update_workflow_node(
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
                    logger.debug("subagent timeout workflow node marking failed: node_id=%s", node_id, exc_info=True)
                return {
                    "error": timeout_error,
                    "task_id": task_id,
                    "role": role,
                }

            result_payload = object_dict(result)
            return result_payload or {"task_id": task_id, "role": role, "status": "done"}

    async def dispatch_subagent(tool_input: JsonObject) -> JsonObject:
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
        prompt_override = _optional_string(tool_input.get("prompt"))
        prev_node_key = _optional_string(tool_input.get("prev_node_key"))

        issue = await cast(_IssueLoader, store).load_codex_issue(issue_id)
        if issue is None:
            return {"error": f"Issue {issue_id} not found"}

        budget_blocked = await _check_budget_gate(issue, tool="dispatch_subagent")
        if budget_blocked is not None:
            return budget_blocked

        exhausted = await _check_redispatch_budget(role, tool="dispatch_subagent")
        if exhausted is not None:
            return exhausted

        async def _pre_dispatch_check() -> JsonObject | None:
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

    async def dispatch_batch(tool_input: JsonObject) -> JsonObject:
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

        issue = await cast(_IssueLoader, store).load_codex_issue(issue_id)
        if issue is None:
            return {"error": f"Issue {issue_id} not found"}

        batch_budget_status, budget_failure = await _compute_budget_status(
            issue,
            tool="dispatch_batch",
        )
        if budget_failure is not None:
            return budget_failure
        if batch_budget_status is not None:
            budget_blocked = await _budget_gate_result(
                issue,
                batch_budget_status,
                tool="dispatch_batch",
            )
            if budget_blocked is not None:
                return budget_blocked

        if not issue.project_id:
            return {"error": f"Issue {issue_id} has no project_id"}
        project = await cast(_ProjectLoader, store).load_project(issue.project_id)
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
        specs: list[JsonObject] = []
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
        # This can only ever REDUCE parallelism, never raise it. If budget status
        # cannot be evaluated, dispatch fails closed instead of falling back open.
        configured_cap = timeouts.max_parallel_dispatch_per_batch()
        cap = configured_cap
        budget_status = batch_budget_status
        if budget_status is None:
            budget_status, budget_failure = await _compute_budget_status(
                issue,
                tool="dispatch_batch",
            )
            if budget_failure is not None:
                return budget_failure
        assert budget_status is not None
        cap = timeouts.budget_supported_concurrency(
            budget_status.remaining_usd,
            configured_cap,
            soft_warn=budget_status.soft_warn,
            over_budget=budget_status.over_budget,
        )
        if budget_status.remaining_usd is not None:
            affordable = int(
                max(0.0, budget_status.remaining_usd)
                // timeouts.estimated_agent_cost_usd()
            )
            if affordable > 0:
                cap = min(cap, affordable)
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
            logger.debug("dispatch batch upstream flush failed: issue_id=%s", issue.id, exc_info=True)

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
                "roles": [str(s.get("role") or "") for s in specs],
            },
        )

        async def _run_one(spec: JsonObject) -> JsonObject:
            agent_key = str(spec.get("agent_key") or "")
            worktree_key = str(spec.get("worktree_key") or "")
            role = str(spec.get("role") or "")
            async with sem:
                worktree_path: str | None = None
                agent_branch: str | None = None
                cleanup_on_exit = False
                try:
                    async def _pre_dispatch_check() -> JsonObject | None:
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
                        prompt_override=_optional_string(spec.get("prompt")),
                        prev_node_key=_optional_string(spec.get("prev_node_key")),
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
                        "worktree_key": worktree_key,
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
                        "worktree_key": worktree_key,
                        "role": role,
                        "branch": agent_branch,
                        "worktree_path": worktree_path,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                finally:
                    if cleanup_on_exit:
                        try:
                            await wm.cleanup_agent_worktree(project, issue, worktree_key)
                        except Exception:  # noqa: BLE001, RUF100
                            logger.debug(
                                "agent worktree cleanup failed: issue_id=%s worktree_key=%s",
                                issue.id,
                                worktree_key,
                                exc_info=True,
                            )

        # return_exceptions=True → partial join: a crashing coroutine does not
        # propagate and kill its siblings (research §3 asyncio pitfall). _run_one
        # already converts in-band failures to result dicts, so this is a final
        # safety net for anything that escapes it.
        gathered = await asyncio.gather(*(_run_one(spec) for spec in specs), return_exceptions=True)

        results: list[JsonObject] = []
        for spec, item in zip(specs, gathered):  # noqa: B905
            if isinstance(item, BaseException):
                results.append(
                    {
                        "agent_key": spec["agent_key"],
                        "worktree_key": spec["worktree_key"],
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
        merge_candidates: list[AgentMergeSpec] = []
        for r in succeeded:
            raw_agent_key = r.get("agent_key")
            raw_branch = r.get("branch")
            if not isinstance(raw_agent_key, str) or not isinstance(raw_branch, str):
                continue
            candidate: AgentMergeSpec = {"agent_key": raw_agent_key, "branch": raw_branch}
            for key in ("worktree_key", "role", "worktree_path"):
                value = r.get(key)
                if isinstance(value, str):
                    candidate[key] = value
            merge_candidates.append(candidate)

        merge_summary: AgentMergeSummary = {
            "merged": [],
            "conflict": None,
            "skipped": [],
            "noop": [],
        }
        merge_error: str | None = None
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
                merge_error = f"{type(exc).__name__}: {exc}"
            await _emit(
                event_bus,
                "conductor_tool",
                {
                    "tool": "dispatch_batch",
                    "status": "merge_complete",
                    "merged": _list_count(merge_summary.get("merged")),
                    "conflict": bool(merge_summary.get("conflict")),
                    "skipped": _list_count(merge_summary.get("skipped")),
                    "noop": _list_count(merge_summary.get("noop")),
                },
            )

        conflict = merge_summary.get("conflict")
        merge_status = (
            "error"
            if merge_error
            else ("conflict" if conflict else ("merged" if merge_summary.get("merged") else "noop"))
        )

        out: JsonObject = {
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
        if merge_error:
            out["merge_error"] = merge_error
            out["note"] = (
                "MERGE ERROR during join: successful agents finished, but their "
                "per-agent worktrees could not be reconciled into the issue branch. "
                "The merge error is preserved in 'merge_error'; inspect the kept "
                "agent worktrees before retrying or finalizing."
            )
        elif not conflict:
            noop_note = ""
            noop_merges = out.get("noop_merges")
            if isinstance(noop_merges, list) and noop_merges:
                noop_keys = [object_dict(n).get("agent_key") for n in noop_merges]
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
            graph = await cast(_WorkflowGraphLoader, store).load_workflow_graph_for_issue(issue_id)
        except Exception:  # noqa: BLE001, RUF100
            return fallback
        for node in getattr(graph, "nodes", None) or []:
            if str(getattr(node, "id", "") or "") == node_id:
                return str(getattr(node, "node_key", "") or "") or fallback
        return fallback

    async def spawn_custom_subagent(tool_input: JsonObject) -> JsonObject:
        payload = {
            "project_id": project_id,
            "role_key": tool_input.get("role_key"),
            "label": tool_input.get("label"),
            "prompt": tool_input.get("prompt"),
            "status": "registered",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "spawn_custom_subagent", **payload})
        return payload

    async def inject_context_into_node(tool_input: JsonObject) -> JsonObject:
        payload = {
            "project_id": project_id,
            "node_key": tool_input.get("node_key"),
            "context": tool_input.get("context"),
            "status": "accepted",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "inject_context_into_node", **payload})
        return payload

    async def request_user_clarification(tool_input: JsonObject) -> JsonObject:
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

    async def finalize_task(tool_input: JsonObject) -> JsonObject:
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
                reason = str(
                    blocked.get("reason")
                    or blocked.get("error")
                    or "success gate rejected finalize_task"
                )
                raw_blocking = blocked.get("blocking_nodes")
                blocking = raw_blocking if isinstance(raw_blocking, list) else []
                msg = f"[finalize rejected] {reason}"
                if blocking:
                    msg += f"\nBlocking nodes: {json.dumps(blocking[:10], default=str)}"
                msg += "\nResolve these nodes before calling finalize_task(status='done')."
                raise ValueError(msg)
        result: JsonObject = {
            "status": status,
            "answer": answer,
            "summary": summary,
        }
        return result

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


def _is_successful_subagent_status(status: object) -> bool:
    return bool(is_task_success_status(str(status or "")))


async def _maybe_await_status(result: Awaitable[None] | None) -> None:
    if result is not None:
        await result


async def _emit(event_bus: object | None, event_type: str, payload: JsonObject) -> None:
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
    await _maybe_await_status(result)


def _tool_definitions() -> list[JsonObject]:
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


def _tool(name: str, description: str, properties: JsonObject, required: list[str]) -> JsonObject:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
