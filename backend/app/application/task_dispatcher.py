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
    CodexIssue,
    CodexTask,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)

logger = logging.getLogger(__name__)


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

    # Check for an existing node for this role (idempotent re-dispatch)
    existing_node = next(
        (
            n for n in graph.nodes
            if (n.node_key == role or n.node_key.startswith(f"{role}#"))
            and n.status in ("done", "failed", "completed")
        ),
        None,
    )
    if existing_node and existing_node.task_id:
        # Already completed — return existing task_id (Conductor will get cached result)
        return existing_node.task_id, existing_node.id

    # Build the task
    effective_prompt = prompt_override
    if not effective_prompt:
        # Fall back to issue title + description (same as _dispatch_node for managed roles)
        issue_body = (issue.description or "").strip()
        effective_prompt = f"{issue.title}\n\n{issue_body}" if issue_body else (issue.title or "")

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
        executor=agent.default_executor or "claude",
        provider=agent.default_provider,
        model=agent.default_model,
        status="pending",
        workspace_path=issue.git_worktree_path,
        git_branch=issue.git_branch,
        git_base_branch=issue.git_base_branch,
        git_worktree_path=issue.git_worktree_path,
        created_at=now,
        updated_at=now,
    )

    # Dynamically add a node to the graph for visualization.
    # We do this by loading current nodes+edges, appending, and re-saving.
    node_id = str(uuid4())
    # Count existing nodes with same role to create unique key
    same_role_count = sum(
        1 for n in graph.nodes
        if n.node_key == role or n.node_key.startswith(f"{role}#")
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
