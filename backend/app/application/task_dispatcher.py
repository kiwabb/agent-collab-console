"""Standalone task dispatcher for Conductor-driven orchestration.

Creates a CodexTask for a given role, optionally adding a dynamic node to the
issue's WorkflowGraph for visualization, then kicks off the task runner.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from inspect import isawaitable
from typing import Protocol
from uuid import uuid4

from app.application.verification_evidence import (
    VERIFICATION_EVIDENCE_ROLES,
    append_acceptance_criteria_context,
)
from app.domain.models import (
    Agent,
    AgentMessage,
    CodexIssue,
    CodexTask,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)

logger = logging.getLogger(__name__)

_ROLE_ALIASES: dict[str, str] = {
    "pm": "product_manager",
    "arch": "architect",
    "eng": "engineer",
    "dev": "engineer",
}

# Per-issue locks serialising the graph-ledger section of dispatch_role
# (load graph → compute node_key from node count → persist task/node/edge).
# Without this, two same-turn parallel dispatches of the same role would each
# read the same node count and mint a COLLIDING node_key. The lock only guards
# the cheap bookkeeping; the slow subagent run happens outside it in the caller.
_issue_dispatch_locks: dict[str, asyncio.Lock] = {}


class DispatchRoleStore(Protocol):
    def list_agents(self, *, workspace_id: str | None = None) -> Awaitable[list[Agent]]: ...

    def load_workflow_graph_for_issue(
        self, issue_id: str
    ) -> Awaitable[WorkflowGraph | None]: ...

    def save_codex_task(self, task: CodexTask) -> Awaitable[None]: ...

    def add_workflow_node(self, node: WorkflowNode) -> Awaitable[None]: ...

    def add_workflow_edge(self, edge: WorkflowEdge) -> Awaitable[None]: ...

    def save_agent_message(self, message: AgentMessage) -> Awaitable[None]: ...

    def update_workflow_node(self, node_id: str, **updates: object) -> Awaitable[None]: ...


class DispatchEventBus(Protocol):
    def append(self, event: dict[str, object]) -> Awaitable[None]: ...


TaskDispatcherFn = Callable[[CodexTask], object | Awaitable[object]]


def _issue_dispatch_lock(issue_id: str) -> asyncio.Lock:
    lock = _issue_dispatch_locks.get(issue_id)
    if lock is None:
        lock = asyncio.Lock()
        _issue_dispatch_locks[issue_id] = lock
    return lock


def normalize_role(role: str) -> str:
    key = role.lower().strip()
    return _ROLE_ALIASES.get(key, key)


def _normalize_role(role: str) -> str:
    return normalize_role(role)


def _summarize_dispatch_body(role: str, prompt: str | None, *, is_fallback: bool = False) -> str:
    if is_fallback or not prompt:
        return f"Dispatch {role}"
    p = prompt.strip()
    if len(p) > 200:
        return p[:200] + "…"
    return p


async def dispatch_role(
    *,
    issue: CodexIssue,
    role: str,
    prompt_override: str | None = None,
    store: DispatchRoleStore,
    task_dispatcher_fn: TaskDispatcherFn | None,
    event_bus: DispatchEventBus | None = None,
    prev_node_key: str | None = None,
    agent_worktree_path: str | None = None,
    batch_key: str | None = None,
    register_completion: bool = False,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
) -> tuple[str, str]:  # (task_id, node_id)
    """Dispatch a role task for Conductor-driven orchestration.

    Creates a CodexTask, dynamically adds a WorkflowNode to the issue's graph
    (for visualization), then invokes `task_dispatcher_fn(task)` to start execution.

    `agent_worktree_path`: when provided (parallel swarm dispatch), the task runs
    in this isolated per-agent worktree instead of the shared issue worktree, so
    concurrent agents don't clobber each other. When omitted (default / serial
    path), behaviour is unchanged: the task uses the shared issue worktree.

    `batch_key`: when provided (parallel swarm dispatch via dispatch_batch), all
    nodes created in the same batch share this key so the UI can group them into a
    parallel swimlane. None for serial dispatches.

    Returns (task_id, node_id). When `register_completion` is True, this function
    registers task_id in TaskCompletionRegistry BEFORE launching the task runner,
    closing a signal-before-register race: a task that completes instantly (e.g.
    an `executor_failed_to_start` fail-fast handshake) could otherwise fire its
    completion signal before the caller registered, and the result would be lost
    until hard_timeout. Callers that await completion must pass
    `register_completion=True`; fire-and-forget callers leave it False so they
    never create an orphan event nobody waits on.
    """
    role = _normalize_role(role)
    agents = await store.list_agents(workspace_id=None)
    agent = next((a for a in agents if a.role_key == role), None)
    if agent is None:
        agent = next((a for a in agents if a.role_key.startswith(f"{role}:")), None)
    if agent is None:
        raise ValueError(f"No agent found for role '{role}'")

    # Build the task (graph-independent) ahead of the locked ledger section.
    effective_prompt = prompt_override
    is_fallback_prompt = False
    if not effective_prompt:
        issue_body = (issue.description or "").strip()
        effective_prompt = f"{issue.title}\n\n{issue_body}" if issue_body else (issue.title or "")
        is_fallback_prompt = True
    if role in VERIFICATION_EVIDENCE_ROLES:
        effective_prompt = append_acceptance_criteria_context(
            effective_prompt,
            issue.acceptance_criteria,
            confirmed=issue.acceptance_criteria_confirmed,
        )

    # The issue-level executor selection (chosen at creation) wins over the agent
    # catalog defaults. When the issue specifies an executor we take its
    # executor/provider/model as a set, so we never mix an issue executor with an
    # agent's provider/model (which would route to the wrong runtime/API).
    if issue.executor:
        task_executor = issue.executor
        task_provider = issue.provider
        task_model = issue.model
    else:
        task_executor = agent.default_executor or "claude"
        task_provider = agent.default_provider
        task_model = agent.default_model

    # Parallel swarm dispatch isolates each agent in its own worktree; the serial
    # path (agent_worktree_path is None) keeps the shared issue worktree as cwd.
    workspace_path = agent_worktree_path or issue.git_worktree_path

    now = datetime.now()
    node_id = str(uuid4())
    task_id_str = str(uuid4())
    task = CodexTask(
        id=task_id_str,
        session_id=issue.session_id,
        project_id=issue.project_id,
        issue_id=issue.id,
        phase=role,
        title=issue.title,
        prompt=effective_prompt,
        role=role,
        executor=task_executor,
        provider=task_provider,
        model=task_model,
        status="pending",
        workspace_path=workspace_path,
        git_branch=issue.git_branch,
        git_base_branch=issue.git_base_branch,
        git_worktree_path=workspace_path,
        trace_id=trace_id,
        span_id=task_id_str,
        parent_span_id=parent_span_id,
        created_at=now,
        updated_at=now,
    )
    task.workflow_node_id = node_id

    # Locked ledger section: count existing same-role nodes → mint a unique
    # node_key (engineer, engineer#1, …) → persist task/node/edge atomically.
    # The lock spans count→add_node so two concurrent same-turn dispatches of the
    # same role can't both read the same count and mint a COLLIDING node_key.
    # Each dispatch still gets a unique key, so the Conductor can legitimately
    # re-dispatch a role (e.g. engineer after QA failure). The slow subagent run
    # happens outside this lock, back in the caller.
    async with _issue_dispatch_lock(issue.id):
        graph = await store.load_workflow_graph_for_issue(issue.id)
        if graph is None:
            raise ValueError(f"No workflow graph for issue {issue.id}")

        same_role_count = sum(
            1 for n in graph.nodes if n.node_key == role or n.node_key.startswith(f"{role}#")
        )
        node_key = role if same_role_count == 0 else f"{role}#{same_role_count}"

        node = WorkflowNode(
            id=node_id,
            graph_id=graph.id,
            node_key=node_key,
            agent_id=agent.id,
            title=f"{role.replace('_', ' ').title()}",
            status="running",
            task_id=task.id,
            batch_key=batch_key,
            started_at=now,
            created_at=now,
            updated_at=now,
        )

        # Add edge from previous node (if any)
        new_edge: WorkflowEdge | None = None
        if prev_node_key:
            new_edge = WorkflowEdge(
                id=str(uuid4()),
                graph_id=graph.id,
                from_node_key=prev_node_key,
                to_node_key=node_key,
                edge_type="sequence",
                created_at=now,
            )

        await store.save_codex_task(task)
        await store.add_workflow_node(node)
        if new_edge:
            await store.add_workflow_edge(new_edge)

    mesh_msg: AgentMessage | None = None
    try:
        from_key = prev_node_key or "conductor"
        mesh_msg = AgentMessage(
            id=str(uuid4()),
            issue_id=issue.id,
            graph_id=graph.id,
            from_node_key=from_key,
            to_node_key=node_key,
            message_type="handoff",
            body=_summarize_dispatch_body(role, effective_prompt, is_fallback=is_fallback_prompt),
            created_at=now,
        )
        await store.save_agent_message(mesh_msg)
    except Exception as exc:  # noqa: BLE001, RUF100
        mesh_msg = None
        logger.warning("dispatch_role mesh write failed: %s", exc)

    # Emit events
    if event_bus is not None:
        try:
            from app.application.task_serialization import serialize_task_payload

            await event_bus.append({"type": "task_created", "task": serialize_task_payload(task)})
            await event_bus.append(
                {
                    "type": "workflow_node_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "node_id": node.id,
                    "node_key": node_key,
                    "status": "running",
                    "task_id": task.id,
                    "batch_key": batch_key,
                }
            )
            if mesh_msg is not None:
                await event_bus.append(
                    {
                        "type": "agent_message_posted",
                        "issue_id": issue.id,
                        "session_id": issue.session_id,
                        "message": {
                            "id": mesh_msg.id,
                            "issue_id": mesh_msg.issue_id,
                            "graph_id": mesh_msg.graph_id,
                            "from_node_key": mesh_msg.from_node_key,
                            "to_node_key": mesh_msg.to_node_key,
                            "message_type": mesh_msg.message_type,
                            "body": mesh_msg.body,
                            "created_at": mesh_msg.created_at.isoformat()
                            if mesh_msg.created_at
                            else None,
                        },
                    }
                )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("dispatch_role emit failed: %s", exc)

    # Register the task in the completion registry BEFORE launching the runner so
    # an instantly-completing task can't signal into the void. Idempotent: the
    # caller (e.g. _run_single_dispatch) may register again with no effect.
    if register_completion:
        from app.application.task_completion_registry import TaskCompletionRegistry

        TaskCompletionRegistry.get().register(task.id)

    # Start task execution
    if task_dispatcher_fn is not None:
        try:
            result = task_dispatcher_fn(task)
            if isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("dispatch_role task runner failed: %s", exc)
            task.status = "failed"
            task.result = f"Task runner failed to start: {exc}"
            task.updated_at = datetime.now()
            await store.save_codex_task(task)
            try:
                await store.update_workflow_node(
                    node.id,
                    status="failed",
                    task_id=task.id,
                    completed_at=datetime.now(),
                )
            except Exception as node_exc:
                logger.warning("dispatch_role failed to mark workflow node failed: %s", node_exc)
            if event_bus is not None:
                try:
                    from app.application.task_status_events import build_task_status_event

                    await event_bus.append(
                        build_task_status_event(task, "failed", result=task.result)
                    )
                    await event_bus.append(
                        {
                            "type": "workflow_node_updated",
                            "issue_id": issue.id,
                            "session_id": issue.session_id,
                            "node_id": node.id,
                            "node_key": node_key,
                            "status": "failed",
                            "task_id": task.id,
                            "batch_key": batch_key,
                        }
                    )
                except Exception as emit_exc:
                    logger.warning("dispatch_role failed to emit runner-start failure: %s", emit_exc)
            if register_completion:
                from app.application.task_completion_registry import TaskCompletionRegistry

                TaskCompletionRegistry.get().signal(
                    task.id,
                    {
                        "status": "failed",
                        "task_id": task.id,
                        "node_id": node_id,
                        "role": task.role,
                        "error": task.result,
                    },
                )

    return task.id, node_id
