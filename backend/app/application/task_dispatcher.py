"""Standalone task dispatcher for Conductor-driven orchestration.

Creates a CodexTask for a given role, optionally adding a dynamic node to the
issue's WorkflowGraph for visualization, then kicks off the task runner.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

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


def _normalize_role(role: str) -> str:
    return _ROLE_ALIASES.get(role.lower().strip(), role)


def _summarize_dispatch_body(role: str, prompt: str | None, *, is_fallback: bool = False) -> str:
    if is_fallback or not prompt:
        return f"Dispatch {role}"
    return prompt.strip()


async def dispatch_role(
    *,
    issue: CodexIssue,
    role: str,
    prompt_override: str | None = None,
    store,
    task_dispatcher_fn,
    event_bus=None,
    prev_node_key: str | None = None,
) -> tuple[str, str]:  # (task_id, node_id)
    """Dispatch a role task for Conductor-driven orchestration.

    Creates a CodexTask, dynamically adds a WorkflowNode to the issue's graph
    (for visualization), then invokes `task_dispatcher_fn(task)` to start execution.

    Returns (task_id, node_id). The caller registers task_id in TaskCompletionRegistry
    before awaiting.
    """
    role = _normalize_role(role)
    agents = await store.list_agents(workspace_id=None)
    agent = next(
        (a for a in agents if a.role_key == role or a.role_key.startswith(role)),
        None,
    )
    if agent is None:
        raise ValueError(f"No agent found for role '{role}'")

    graph = await store.load_workflow_graph_for_issue(issue.id)
    if graph is None:
        raise ValueError(f"No workflow graph for issue {issue.id}")

    # Compute node_key: each dispatch gets a unique key (engineer, engineer#1, …)
    # so Conductor can legitimately re-dispatch the same role (e.g. after QA failure).
    same_role_count = sum(
        1 for n in graph.nodes
        if n.node_key == role or n.node_key.startswith(f"{role}#")
    )
    node_key = role if same_role_count == 0 else f"{role}#{same_role_count}"

    # Build the task
    effective_prompt = prompt_override
    is_fallback_prompt = False
    if not effective_prompt:
        issue_body = (issue.description or "").strip()
        effective_prompt = f"{issue.title}\n\n{issue_body}" if issue_body else (issue.title or "")
        is_fallback_prompt = True

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

    now = datetime.now()
    task = CodexTask(
        id=str(uuid4()),
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
        workspace_path=issue.git_worktree_path,
        git_branch=issue.git_branch,
        git_base_branch=issue.git_base_branch,
        git_worktree_path=issue.git_worktree_path,
        created_at=now,
        updated_at=now,
    )

    node_id = str(uuid4())

    node = WorkflowNode(
        id=node_id,
        graph_id=graph.id,
        node_key=node_key,
        agent_id=agent.id,
        title=f"{role.replace('_', ' ').title()}",
        status="running",
        task_id=task.id,
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    task.workflow_node_id = node_id

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
    except Exception as exc:  # noqa: BLE001
        mesh_msg = None
        logger.warning("dispatch_role mesh write failed: %s", exc)

    # Emit events
    if event_bus is not None:
        try:
            from app.application.task_serialization import serialize_task_payload
            await event_bus.append({"type": "task_created", "task": serialize_task_payload(task)})
            await event_bus.append({
                "type": "workflow_node_updated",
                "issue_id": issue.id,
                "session_id": issue.session_id,
                "node_id": node.id,
                "node_key": node_key,
                "status": "running",
                "task_id": task.id,
            })
            if mesh_msg is not None:
                await event_bus.append({
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
                        "created_at": mesh_msg.created_at.isoformat() if mesh_msg.created_at else None,
                    },
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("dispatch_role emit failed: %s", exc)

    # Start task execution
    if task_dispatcher_fn is not None:
        try:
            result = task_dispatcher_fn(task)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            logger.warning("dispatch_role task runner failed: %s", exc)

    return task.id, node_id
