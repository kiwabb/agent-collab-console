"""Workflow DAG scheduler.

Owns the lifecycle of a WorkflowGraph once started: detects which nodes are
ready (deps satisfied), dispatches them as CodexTasks via the existing
task runner, watches for completion via the event bus, and walks the graph
forward until done.

PR3 ships a minimal vertical slice — sequence/parallel-fanout edges are
honored; refine-loop and retry-on-fail land in PR6 alongside the Replanner.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Iterable
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


class WorkflowSchedulerError(RuntimeError):
    pass


class WorkflowScheduler:
    """Dispatches DAG nodes for a single issue.

    Construction is cheap; the actual loop runs inside start_graph / settle.
    """

    def __init__(self, store, task_dispatcher=None, event_bus=None) -> None:
        self.store = store
        self._task_dispatcher = task_dispatcher  # callable(task) -> awaitable, optional
        self._event_bus = event_bus

    # --- Public API ---

    async def start_graph(self, graph_id: str) -> WorkflowGraph:
        graph = await self._require_graph(graph_id)
        if graph.status not in {"draft", "paused"}:
            return graph
        graph.status = "running"
        graph.locked_at = datetime.now()
        await self.store.save_workflow_graph(graph)
        await self.settle(graph_id)
        return await self._require_graph(graph_id)

    async def settle(self, graph_id: str) -> WorkflowGraph:
        """Advance the DAG: mark blocked/ready nodes, dispatch ready ones.

        Idempotent — running it twice with no state change is a no-op.
        """
        graph = await self._require_graph(graph_id)
        # If a replan is pending for this graph, pause dispatch until the user resolves.
        pending = await self.store.list_pending_replans(graph_id)
        if pending:
            return graph

        nodes_by_key = {n.node_key: n for n in graph.nodes}
        edges_by_target: dict[str, list[WorkflowEdge]] = {}
        for e in graph.edges:
            edges_by_target.setdefault(e.to_node_key, []).append(e)

        for node in graph.nodes:
            new_status = self._compute_node_status(node, edges_by_target.get(node.node_key, []), nodes_by_key)
            if new_status and new_status != node.status:
                await self.store.update_workflow_node(node.id, status=new_status)
                node.status = new_status

        # Dispatch all ready nodes (concurrent dispatch handles parallel-fanout naturally).
        ready_nodes = [n for n in graph.nodes if n.status == "ready"]
        if ready_nodes:
            issue = await self.store.load_codex_issue(graph.issue_id)
            if issue is None:
                raise WorkflowSchedulerError(f"Graph {graph_id} references missing issue {graph.issue_id}")
            agents_by_id = {a.id: a for a in await self.store.list_agents(workspace_id=None)}
            await asyncio.gather(*[
                self._dispatch_node(node, issue, agents_by_id) for node in ready_nodes
            ])

        # If all nodes are terminal, mark the graph done/failed.
        await self._maybe_finalize(graph)
        return await self._require_graph(graph_id)

    async def on_task_completed(self, task: CodexTask) -> None:
        """Hook called by the task runner / event handler once a task ends.

        Looks up the workflow_node for the task, updates its status, then:
          1. consider retry-on-fail edges (auto-retry without user input)
          2. consider replan triggers (suspend graph, surface diff to user)
          3. fall through to a regular settle pass
        """
        if not getattr(task, "workflow_node_id", None):
            return
        node = await self.store.find_node_by_task_id(task.id)
        if node is None:
            return
        terminal = self._task_status_to_node_status(task.status)
        if terminal is None:
            return
        await self.store.update_workflow_node(
            node.id,
            status=terminal,
            completed_at=datetime.now(),
        )
        node.status = terminal
        graph = await self.store.load_workflow_graph(node.graph_id)
        if graph is None:
            return

        # 1. retry-on-fail: bring the failed node back to pending if any
        #    incoming retry-on-fail edge exists AND we're under max_retries.
        if terminal == "failed" and node.retries < node.max_retries:
            retry_edges = [
                e for e in graph.edges
                if e.to_node_key == node.node_key and e.edge_type == "retry-on-fail"
            ]
            if retry_edges:
                await self.store.update_workflow_node(
                    node.id,
                    status="pending",
                    retries=node.retries + 1,
                )
                await self.settle(graph.id)
                return

        # 2. replan triggers — only when the completed agent has the flag set.
        await self._maybe_open_replan(graph, node, terminal)

        # 3. ordinary settle pass.
        await self.settle(graph.id)

    async def _maybe_open_replan(self, graph: WorkflowGraph, node: WorkflowNode, terminal: str) -> None:
        """Check whether this node's completion should suspend the graph for replan."""
        if self.store is None:
            return
        agents = await self.store.list_agents(workspace_id=None)
        agents_by_id = {a.id: a for a in agents}
        agent = agents_by_id.get(node.agent_id)
        if agent is None:
            return
        trigger_reason: str | None = None
        if terminal == "done" and agent.triggers_replan_on_done:
            trigger_reason = "node_done"
        elif terminal == "failed" and agent.triggers_replan_on_fail:
            trigger_reason = "node_failed"
        if trigger_reason is None:
            return

        from app.application.workflow_orchestrator import WorkflowOrchestrator
        orchestrator = WorkflowOrchestrator(store=self.store)
        diff = await orchestrator.replan(graph, node, trigger_reason, agents=agents)
        if not diff.get("has_changes"):
            return
        from app.domain.models import GraphReplanPending
        replan = GraphReplanPending(
            id=str(uuid4()),
            graph_id=graph.id,
            triggered_by_node_key=node.node_key,
            trigger_reason=trigger_reason,
            diff_json=json.dumps(diff, ensure_ascii=False, default=str),
            rationale=diff.get("rationale"),
            status="pending",
            created_at=datetime.now(),
        )
        await self.store.save_replan_pending(replan)
        # NOTE: settle() will see this pending replan and refuse to dispatch
        # until it's confirmed/rejected.

    async def apply_replan(self, replan_id: str, decision: str) -> WorkflowGraph:
        """Resolve a pending replan (decision='confirmed'|'rejected') and resume settle."""
        if decision not in {"confirmed", "rejected"}:
            raise ValueError(f"decision must be 'confirmed' or 'rejected', got {decision!r}")
        # Find the replan row first (so we can grab its diff before marking resolved).
        conn = await self.store._get_conn()
        import aiosqlite
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM graph_replan_pending WHERE id = ?", (replan_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            raise WorkflowSchedulerError(f"Replan {replan_id} not found")
        if row["status"] != "pending":
            raise WorkflowSchedulerError(f"Replan {replan_id} already resolved")
        graph_id = row["graph_id"]
        diff = json.loads(row["diff_json"]) if row["diff_json"] else {}
        if decision == "confirmed":
            await self._apply_diff_to_graph(graph_id, diff)
        ok = await self.store.resolve_replan(replan_id, decision)
        if not ok:
            raise WorkflowSchedulerError(f"Replan {replan_id} could not be resolved")
        # Resume execution
        await self.settle(graph_id)
        return await self._require_graph(graph_id)

    async def _apply_diff_to_graph(self, graph_id: str, diff: dict) -> None:
        graph = await self._require_graph(graph_id)
        done_keys = {n.node_key for n in graph.nodes if n.status == "done"}
        new_nodes = list(graph.nodes)
        new_edges = list(graph.edges)
        from app.domain.models import WorkflowEdge, WorkflowNode
        now = datetime.now()
        for n in diff.get("added_nodes", []):
            new_nodes.append(WorkflowNode(
                id=str(uuid4()),
                graph_id=graph_id,
                node_key=n["node_key"],
                agent_id=n["agent_id"],
                title=n.get("title"),
                status="pending",
                created_at=now,
            ))
        for e in diff.get("added_edges", []):
            new_edges.append(WorkflowEdge(
                id=str(uuid4()),
                graph_id=graph_id,
                from_node_key=e["from_node_key"],
                to_node_key=e["to_node_key"],
                edge_type=e.get("edge_type") or "sequence",
                condition_expr=e.get("condition_expr"),
                created_at=now,
            ))
        # Safety: never drop a done node.
        removed_keys = [k for k in diff.get("removed_node_keys", []) if k not in done_keys]
        if removed_keys:
            new_nodes = [n for n in new_nodes if n.node_key not in removed_keys]
            new_edges = [e for e in new_edges if e.from_node_key not in removed_keys and e.to_node_key not in removed_keys]
        # Rebuild dag_json so the persisted source of truth stays in sync.
        graph.dag_json = json.dumps({
            "meta": {"created_by": "replanner"},
            "nodes": [{"node_key": n.node_key, "agent_id": n.agent_id, "role_key": n.node_key, "title": n.title} for n in new_nodes],
            "edges": [{"from_node_key": e.from_node_key, "to_node_key": e.to_node_key, "edge_type": e.edge_type, "condition_expr": e.condition_expr} for e in new_edges],
        }, ensure_ascii=False, default=str)
        await self.store.save_workflow_graph(graph, nodes=new_nodes, edges=new_edges)

    # --- Internal helpers ---

    async def _require_graph(self, graph_id: str) -> WorkflowGraph:
        graph = await self.store.load_workflow_graph(graph_id)
        if graph is None:
            raise WorkflowSchedulerError(f"Workflow graph {graph_id} not found")
        return graph

    def _compute_node_status(
        self,
        node: WorkflowNode,
        incoming_edges: list[WorkflowEdge],
        nodes_by_key: dict[str, WorkflowNode],
    ) -> str | None:
        if node.status in {"running", "done", "failed", "skipped"}:
            return None
        # Only sequence and parallel-fanout edges gate readiness. Refine-loop
        # back-edges are explicitly *not* dependencies — they exist to allow
        # rework cycles without breaking topo order.
        gating = [e for e in incoming_edges if e.edge_type in {"sequence", "parallel-fanout"}]
        if not gating:
            return "ready"
        all_done = all(
            (parent := nodes_by_key.get(e.from_node_key)) is not None
            and parent.status == "done"
            for e in gating
        )
        return "ready" if all_done else "blocked"

    def _task_status_to_node_status(self, task_status: str) -> str | None:
        if task_status == "done":
            return "done"
        if task_status in {"failed", "error"}:
            return "failed"
        return None

    async def _dispatch_node(
        self,
        node: WorkflowNode,
        issue: CodexIssue,
        agents_by_id: dict[str, Agent],
    ) -> None:
        agent = agents_by_id.get(node.agent_id)
        if agent is None:
            logger.warning("Workflow node %s references missing agent %s — skipping", node.id, node.agent_id)
            await self.store.update_workflow_node(node.id, status="skipped")
            return

        prompt = node.prompt_override or self._render_prompt_template(agent, issue, node)
        # Inherit worktree/git state from the issue so the runner can locate
        # artifacts. Falls back to None when the issue has no worktree yet
        # (tests, ephemeral issues) — the runner should tolerate that.
        task = CodexTask(
            id=str(uuid4()),
            session_id=issue.session_id,
            project_id=issue.project_id,
            issue_id=issue.id,
            phase=agent.role_key,  # Free-form tag now; kept for backward compat with old kanban
            title=node.title or agent.name,
            prompt=prompt,
            role=agent.role_key,
            executor=agent.default_executor or "codex",
            provider=agent.default_provider,
            model=agent.default_model,
            status="pending",
            workspace_path=issue.git_worktree_path,
            git_branch=issue.git_branch,
            git_base_branch=issue.git_base_branch,
            git_worktree_path=issue.git_worktree_path,
            workflow_node_id=node.id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await self.store.save_codex_task(task)
        await self.store.update_workflow_node(
            node.id,
            status="running",
            task_id=task.id,
            started_at=datetime.now(),
        )
        if self._task_dispatcher is not None:
            # Best-effort: the dispatcher may be synchronous (test fakes) or
            # async (production task_runner). If it raises, surface the
            # failure on the node so the rest of the graph isn't stuck.
            try:
                result = self._task_dispatcher(task)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                logger.warning("Workflow dispatcher failed for node %s: %s", node.node_key, exc)
                await self.store.update_workflow_node(
                    node.id,
                    status="failed",
                    completed_at=datetime.now(),
                )

    def _render_prompt_template(self, agent: Agent, issue: CodexIssue, node: WorkflowNode) -> str:
        """Render a system-prompt template with simple field substitution.

        Built-in agents store the marker `[builtin:<role>]`. For those we hand
        back a placeholder string — the runtime falls back to RoleWorkflowService
        for the actual prompt. Custom agents get real interpolation.
        """
        template = agent.system_prompt_template or ""
        if template.startswith("[builtin:"):
            return template  # runtime hook will substitute via RoleWorkflowService
        return (
            template
            .replace("{issue_title}", issue.title or "")
            .replace("{issue_description}", issue.description or "")
            .replace("{role_key}", agent.role_key)
            .replace("{node_key}", node.node_key)
        )

    async def _maybe_finalize(self, graph: WorkflowGraph) -> None:
        latest = await self.store.load_workflow_graph(graph.id)
        if latest is None:
            return
        statuses = {n.status for n in latest.nodes}
        if statuses and statuses <= {"done", "skipped"}:
            if latest.status != "done":
                latest.status = "done"
                await self.store.save_workflow_graph(latest)
        elif "failed" in statuses and not any(s in {"pending", "blocked", "ready", "running"} for s in statuses):
            if latest.status != "failed":
                latest.status = "failed"
                await self.store.save_workflow_graph(latest)


# Convenience for callers building a graph from a proposed DAG JSON
async def materialize_graph_from_dag(
    store,
    issue_id: str,
    dag: dict,
    created_by: str = "user",
) -> WorkflowGraph:
    """Persist a fresh graph from a proposed DAG payload."""
    graph_id = str(uuid4())
    now = datetime.now()
    nodes: list[WorkflowNode] = []
    edges: list[WorkflowEdge] = []
    for n in dag.get("nodes", []):
        nodes.append(WorkflowNode(
            id=str(uuid4()),
            graph_id=graph_id,
            node_key=n["node_key"],
            agent_id=n["agent_id"],
            title=n.get("title") or n.get("role_key"),
            prompt_override=n.get("prompt"),
            status="pending",
            created_at=now,
        ))
    for e in dag.get("edges", []):
        edges.append(WorkflowEdge(
            id=str(uuid4()),
            graph_id=graph_id,
            from_node_key=e["from_node_key"],
            to_node_key=e["to_node_key"],
            edge_type=e.get("edge_type") or "sequence",
            condition_expr=e.get("condition_expr"),
            created_at=now,
        ))
    graph = WorkflowGraph(
        id=graph_id,
        issue_id=issue_id,
        dag_json=json.dumps(dag, ensure_ascii=False),
        status="draft",
        created_by=created_by,
        created_at=now,
        updated_at=now,
        nodes=nodes,
        edges=edges,
    )
    await store.save_workflow_graph(graph, nodes=nodes, edges=edges)
    return graph
