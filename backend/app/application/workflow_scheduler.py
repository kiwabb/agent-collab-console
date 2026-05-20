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
import os
from datetime import datetime
from typing import Iterable
from uuid import uuid4

from app.application.agent_catalog.catalog import (
    CUSTOM_PREFIX,
    SPECIALIST_PREFIX,
    AgentCatalog,
    AgentDefinition,
)
from app.domain.models import (
    Agent,
    CodexIssue,
    CodexTask,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from app.application.role_workflow_service import ENGINEER_ROLES

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

    async def _emit_node_event(self, node: WorkflowNode, issue: CodexIssue | None) -> None:
        """Best-effort emit of workflow_node_updated so the frontend DAG/
        IssueDetail can refetch immediately on transitions (pending→running,
        running→done/failed, qa-rework→pending) instead of waiting for the
        next poll cycle."""
        if self._event_bus is None or issue is None:
            return
        try:
            await self._event_bus.append({
                "type": "workflow_node_updated",
                "issue_id": issue.id,
                "session_id": issue.session_id,
                "node_id": node.id,
                "node_key": node.node_key,
                "status": node.status,
                "task_id": node.task_id,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("workflow_node_updated emit failed: %s", exc)

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

        issue = await self.store.load_codex_issue(graph.issue_id)
        if issue is not None and issue.status == "awaiting_approval":
            return await self._require_graph(graph_id)

        priority_node_keys: set[str] = set()
        if issue is not None:
            priority_node_keys = await self._apply_pending_conductor_dispatches(graph, issue)
            graph = await self._require_graph(graph_id)

        # Dispatch all ready nodes (concurrent dispatch handles parallel-fanout naturally).
        ready_nodes = [n for n in graph.nodes if n.status == "ready"]
        if priority_node_keys:
            ready_nodes = [n for n in ready_nodes if n.node_key in priority_node_keys]
        if ready_nodes:
            issue = issue or await self.store.load_codex_issue(graph.issue_id)
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
          2. handle QA-fail → Engineer auto-rework (no user prompt; bounded
             by engineer.max_retries)
          3. consider replan triggers (suspend graph, surface diff to user)
          4. fall through to a regular settle pass
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
        # Notify subscribers of the node transition so the DAG / IssueDetail
        # views update in the same tick as task_status — without this, the
        # graph still ticks via polling.
        issue_for_event = None
        try:
            issue_for_event = await self.store.load_codex_issue(graph.issue_id)
            await self._emit_node_event(node, issue_for_event)
        except Exception:  # noqa: BLE001
            pass

        # Conductor observation pass. Runs on every task completion. May
        # return a decision dict {action, reason, note?}. When action=="escalate"
        # we pause the workflow — no auto-rework, no auto-finalize, the user
        # has to take manual action (retry from DAG tab, steer, abandon).
        # Wrapped so any failure here can't break the scheduler.
        conductor_decision: dict | None = None
        conductor_graph_mutated = False
        try:
            from app.application.conductor_supervisor import ConductorSupervisor
            from app.application.subagent_result_builder import build_subagent_result
            supervisor = ConductorSupervisor(store=self.store, event_bus=self._event_bus)
            subagent_result = build_subagent_result(
                task=task,
                node=node,
                doc=getattr(task, "_subagent_doc", None),
            )
            conductor_decision = await supervisor.observe(
                result=subagent_result,
                node_status=terminal,
                graph=graph,
                issue=issue_for_event,
            )
            if conductor_decision is not None and issue_for_event is not None:
                await self._record_conductor_decision_state(
                    issue=issue_for_event,
                    task=task,
                    node=node,
                    decision=conductor_decision,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("conductor observation failed: %s", exc)

        # Conductor escalation veto: bail before any of the auto-rework /
        # finalize machinery so the workflow visibly halts and the user gets
        # to decide what to do next. Issue stays in_progress; the failed
        # node stays failed; DAG retry button is the manual resume path.
        if conductor_decision and conductor_decision.get("action") == "escalate":
            logger.info(
                "Conductor escalated after task %s (role=%s) — pausing workflow",
                task.id, task.role,
            )
            if issue_for_event is not None and self._event_bus is not None:
                try:
                    await self._event_bus.append({
                        "type": "issue_updated",
                        "issue_id": issue_for_event.id,
                        "session_id": issue_for_event.session_id,
                        "conductor_paused": True,
                    })
                except Exception:  # noqa: BLE001
                    pass
            return

        # Conductor graph-mutation actions (insert_node / reroute).
        # CONDUCTOR_AUTONOMY env: "off" | "suggest" (default) | "autonomous"
        if conductor_decision and conductor_decision.get("action") in {"insert_node", "reroute"}:
            autonomy = os.getenv("CONDUCTOR_AUTONOMY", "suggest").lower()
            if autonomy != "off":
                diff = conductor_decision.get("diff") or {}
                if autonomy == "autonomous" and diff:
                    try:
                        await self._apply_diff_to_graph(graph.id, diff)
                        conductor_graph_mutated = True
                        logger.info(
                            "Conductor auto-applied %s diff to graph %s",
                            conductor_decision.get("action"), graph.id,
                        )
                        if self._event_bus is not None and issue_for_event is not None:
                            try:
                                await self._event_bus.append({
                                    "type": "graph_mutated",
                                    "issue_id": issue_for_event.id,
                                    "session_id": issue_for_event.session_id,
                                    "graph_id": graph.id,
                                    "action": conductor_decision.get("action"),
                                    "reason": conductor_decision.get("reason"),
                                })
                            except Exception:  # noqa: BLE001
                                pass
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Conductor autonomous diff apply failed: %s", exc)
                elif autonomy == "suggest" and diff:
                    # Create a GraphReplanPending so the user sees the suggestion in the UI.
                    try:
                        from app.domain.models import GraphReplanPending
                        replan = GraphReplanPending(
                            id=str(uuid4()),
                            graph_id=graph.id,
                            triggered_by_node_key=node.node_key,
                            trigger_reason=f"conductor_{conductor_decision.get('action')}",
                            diff_json=json.dumps(diff, ensure_ascii=False, default=str),
                            rationale=conductor_decision.get("reason"),
                            status="pending",
                            created_at=datetime.now(),
                        )
                        await self.store.save_replan_pending(replan)
                        logger.info(
                            "Conductor suggested %s — created replan %s for graph %s",
                            conductor_decision.get("action"), replan.id, graph.id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Conductor suggest replan save failed: %s", exc)

        # Conductor agent-spawn actions use the same graph-mutation path as
        # replans, but derive the node/agent from the local agent catalog.
        if conductor_decision and conductor_decision.get("action") in {"spawn_specialist", "spawn_custom"}:
            autonomy = os.getenv("CONDUCTOR_AUTONOMY", "suggest").lower()
            if autonomy != "off":
                try:
                    diff = await self._build_conductor_spawn_diff(
                        graph=graph,
                        source_node=node,
                        decision=conductor_decision,
                    )
                    if autonomy == "autonomous" and diff:
                        await self._apply_diff_to_graph(graph.id, diff)
                        conductor_graph_mutated = True
                        logger.info(
                            "Conductor auto-spawned %s on graph %s",
                            conductor_decision.get("action"), graph.id,
                        )
                        if self._event_bus is not None and issue_for_event is not None:
                            try:
                                await self._event_bus.append({
                                    "type": "graph_mutated",
                                    "issue_id": issue_for_event.id,
                                    "session_id": issue_for_event.session_id,
                                    "graph_id": graph.id,
                                    "action": conductor_decision.get("action"),
                                    "reason": conductor_decision.get("reason"),
                                })
                            except Exception:  # noqa: BLE001
                                pass
                    elif autonomy == "suggest" and diff:
                        from app.domain.models import GraphReplanPending
                        replan = GraphReplanPending(
                            id=str(uuid4()),
                            graph_id=graph.id,
                            triggered_by_node_key=node.node_key,
                            trigger_reason=f"conductor_{conductor_decision.get('action')}",
                            diff_json=json.dumps(diff, ensure_ascii=False, default=str),
                            rationale=conductor_decision.get("reason"),
                            status="pending",
                            created_at=datetime.now(),
                        )
                        await self.store.save_replan_pending(replan)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Conductor spawn handling failed: %s", exc)

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

        # 2. QA failure → Engineer auto-rework. The QA report on disk is the
        #    feedback channel; we just reset the relevant nodes and settle.
        if await self._maybe_trigger_qa_rework(graph, node, terminal):
            return

        # 2.5. Engineer critique → Architect re-run. If the engineer set
        #      architect_critique in its output, the role_workflow_service
        #      already persisted the AgentMessage; we now reset Architect so
        #      it can revise the design before Engineer re-runs.
        if await self._maybe_trigger_peer_critique(graph, node, terminal, task):
            return

        # 3. replan triggers — only when the completed agent has the flag set.
        if not conductor_graph_mutated:
            await self._maybe_open_replan(graph, node, terminal)

        # 3.5 plan-first gate — pause after Product Manager until the user
        # approves the plan summary.
        if await self._maybe_pause_for_plan_approval(graph, node, terminal):
            return

        # 3.6 QA-pass gate — once QA is done, pause for the human to confirm
        # before flipping the issue to awaiting_merge / completed.
        if await self._maybe_pause_for_qa_review(graph, node, terminal):
            return

        # 4. ordinary settle pass.
        await self.settle(graph.id)

    async def _maybe_trigger_qa_rework(
        self, graph: WorkflowGraph, completed_node: WorkflowNode, terminal: str
    ) -> bool:
        """When QA fails, automatically reset the upstream Engineer node so it
        re-runs with the QA report as feedback. Returns True if a rework was
        dispatched (caller should NOT continue to replan/settle paths).

        Bounded by `engineer.max_retries` so we can't loop forever. The QA
        report is already on disk at qa/qa_report.md and is read at
        Engineer-prompt-build time via `task.review_comment`.
        """
        if terminal != "failed":
            return False
        # Identify whether the completed node is QA. Use both role hints
        # available — node_key (canonical for built-in agents) and the
        # underlying agent.role_key (in case node_key was customised).
        if completed_node.node_key != "qa":
            agents = await self.store.list_agents(workspace_id=None)
            agent = next((a for a in agents if a.id == completed_node.agent_id), None)
            if agent is None or agent.role_key != "qa":
                return False

        engineer_node = next(
            (n for n in graph.nodes if n.node_key == "engineer"), None
        )
        if engineer_node is None:
            return False
        if engineer_node.retries >= max(engineer_node.max_retries, 1):
            logger.info(
                "QA failed but engineer rework budget exhausted (retries=%s/%s) — "
                "falling through to replanner",
                engineer_node.retries, engineer_node.max_retries,
            )
            return False

        # Best-effort terminate any still-alive Engineer process before reset.
        if engineer_node.task_id:
            try:
                from app.bootstrap import get_codex_process_manager
                mgr = get_codex_process_manager()
                if mgr is not None:
                    await mgr.terminate_task(engineer_node.task_id)
            except Exception as exc:
                logger.warning(
                    "terminate engineer task %s before rework failed: %s",
                    engineer_node.task_id, exc,
                )

        # Reset both nodes so the scheduler re-fires Engineer first, then QA
        # naturally becomes ready again once Engineer is done.
        await self.store.update_workflow_node(
            engineer_node.id,
            status="pending",
            retries=engineer_node.retries + 1,
            completed_at=None,
        )
        engineer_node.status = "pending"
        await self.store.update_workflow_node(
            completed_node.id,
            status="pending",
            completed_at=None,
        )
        completed_node.status = "pending"
        logger.info(
            "QA failed → resetting engineer for rework (attempt %s/%s)",
            engineer_node.retries + 1, engineer_node.max_retries,
        )
        # Tell the UI the graph just re-armed for rework so the DAG redraws
        # before the next dispatch tick.
        try:
            issue_for_event = await self.store.load_codex_issue(graph.issue_id)
            await self._emit_node_event(engineer_node, issue_for_event)
            await self._emit_node_event(completed_node, issue_for_event)
        except Exception:  # noqa: BLE001
            pass
        await self.settle(graph.id)
        return True

    async def _maybe_trigger_peer_critique(
        self,
        graph: WorkflowGraph,
        completed_node: WorkflowNode,
        terminal: str,
        task,
    ) -> bool:
        """When an Engineer files an architect_critique, reset Architect so it can revise.

        The AgentMessage was already persisted by RoleWorkflowService._record_critique before
        this method is called. We check the DB for a recent critique message on this issue to
        decide whether to trigger the loop. Returns True if the loop was armed.
        """
        if terminal not in ("done", "partial"):
            return False
        # Only engineer roles can critique the architect.
        role = getattr(task, "role", "")
        if role not in ENGINEER_ROLES:
            return False

        # Check if a critique was just recorded.
        if not hasattr(self.store, "list_agent_messages"):
            return False
        messages = await self.store.list_agent_messages(task.issue_id)
        # Find a critique from this engineer role that hasn't already triggered a rework
        # (to avoid infinite loops, limit to 1 critique per engineer node).
        critiques = [m for m in messages if m.message_type == "critique" and m.from_node_key == role]
        if not critiques:
            return False
        # Already had a critique and architect has run again → don't re-trigger.
        architect_node = next(
            (n for n in graph.nodes if n.node_key == "architect"), None
        )
        if architect_node is None:
            return False
        # If architect has already been reset for rework more than once, give up.
        if architect_node.retries >= 2:
            logger.info(
                "Architect already reworked %s times — not re-triggering peer critique",
                architect_node.retries,
            )
            return False

        # The critique message was just saved; we re-fetch to get the most recent one.
        latest_critique = critiques[-1]

        # Surface critique as review_comment on the issue so the architect prompt
        # builder picks it up under "REWORK REQUIRED" section.
        try:
            issue = await self.store.load_codex_issue(graph.issue_id)
            if issue is not None:
                issue.review_comment = (
                    f"[ENGINEER CRITIQUE] The Engineer flagged a critical design gap:\n\n"
                    f"{latest_critique.body}\n\n"
                    "Please revise your architecture to address the above before Engineer re-runs."
                )
                await self.store.save_codex_issue(issue)
        except Exception as exc:  # noqa: BLE001
            logger.warning("_maybe_trigger_peer_critique: failed to update issue review_comment: %s", exc)

        # Reset architect node so it re-runs with the critique.
        await self.store.update_workflow_node(
            architect_node.id,
            status="pending",
            retries=architect_node.retries + 1,
            completed_at=None,
        )
        architect_node.status = "pending"
        # Also reset the engineer node so it re-runs after architect.
        await self.store.update_workflow_node(
            completed_node.id,
            status="pending",
            completed_at=None,
        )
        completed_node.status = "pending"
        logger.info(
            "Engineer critique → resetting architect for design revision (attempt %s)",
            architect_node.retries,
        )
        try:
            issue_for_event = await self.store.load_codex_issue(graph.issue_id)
            await self._emit_node_event(architect_node, issue_for_event)
            await self._emit_node_event(completed_node, issue_for_event)
        except Exception:  # noqa: BLE001
            pass
        await self.settle(graph.id)
        return True

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

    async def _maybe_pause_for_qa_review(
        self, graph: WorkflowGraph, node: WorkflowNode, terminal: str
    ) -> bool:
        """When QA completes successfully, pause the graph in `awaiting_review`
        so the human can audit the QA report and either approve (→ awaiting_merge)
        or reject (→ engineer rework).

        Reject path is handled by the /codex/issues/{id}/qa-review endpoint —
        it reuses the same node-reset logic as `_maybe_trigger_qa_rework`.
        """
        if terminal != "done":
            return False
        # Match QA node by canonical key or agent.role_key fallback.
        if node.node_key != "qa":
            agents = await self.store.list_agents(workspace_id=None)
            agent = next((a for a in agents if a.id == node.agent_id), None)
            if agent is None or agent.role_key != "qa":
                return False

        issue = await self.store.load_codex_issue(graph.issue_id)
        if issue is None:
            return False
        if issue.status in {"awaiting_review", "awaiting_merge", "completed"}:
            return True  # already past this gate; don't double-fire
        issue.status = "awaiting_review"
        issue.current_phase = "done"
        issue.updated_at = datetime.now()
        await self.store.save_codex_issue(issue)
        if self._event_bus is not None:
            try:
                await self._event_bus.append({
                    "type": "issue_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "status": issue.status,
                    "current_phase": issue.current_phase,
                })
            except Exception:  # noqa: BLE001
                pass
        logger.info("QA-review gate engaged for issue %s", issue.id)
        return True

    async def _maybe_pause_for_plan_approval(
        self, graph: WorkflowGraph, node: WorkflowNode, terminal: str
    ) -> bool:
        if terminal != "done":
            return False
        agents = await self.store.list_agents(workspace_id=None)
        agent = next((a for a in agents if a.id == node.agent_id), None)
        if agent is None or agent.role_key != "product_manager":
            return False
        issue = await self.store.load_codex_issue(graph.issue_id)
        if issue is None:
            return False
        if not await self._is_plan_first_enabled(issue.session_id):
            return False

        plan_summary = await self._read_pm_plan_summary(issue)
        issue.review_comment = plan_summary or (
            "[PLAN] PM 阶段完成，请确认 PRD 后继续"
        )
        issue.current_phase = "architecture"
        issue.status = "awaiting_approval"
        issue.updated_at = datetime.now()
        await self.store.save_codex_issue(issue)
        if self._event_bus is not None:
            try:
                await self._event_bus.append({
                    "type": "issue_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "status": issue.status,
                    "current_phase": issue.current_phase,
                    "review_comment": issue.review_comment,
                })
            except Exception:  # noqa: BLE001
                pass
        logger.info("Plan-first gate engaged for issue %s", issue.id)
        return True

    async def _is_plan_first_enabled(self, session_id: str) -> bool:
        workspace = await self.store.load_codex_session(session_id)
        settings = getattr(workspace, "settings", None) or {}
        return bool(settings.get("plan_first_pm", True))

    async def _read_pm_plan_summary(self, issue: CodexIssue) -> str | None:
        if not getattr(issue, "git_worktree_path", None):
            return None
        try:
            from app.application.issue_artifact_documents import IssueArtifactDocuments
            docs = IssueArtifactDocuments()
            path = docs.pm_prd_json_path(issue.git_worktree_path, issue.id)
            if not path.exists():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            summary = payload.get("plan_summary") or []
            if not isinstance(summary, list):
                return None
            bullets = [str(item).strip() for item in summary if str(item).strip()]
            if not bullets:
                return None
            return "\n".join(
                item if item.startswith("-") else f"- {item}"
                for item in bullets[:10]
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to read plan summary for issue %s: %s", issue.id, exc)
            return None

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
                prompt_override=n.get("prompt"),
                status="pending",
                max_retries=int(n.get("max_retries") or 1),
                instance_index=int(n.get("instance_index") or 0),
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
            "nodes": [
                {
                    "node_key": n.node_key,
                    "agent_id": n.agent_id,
                    "role_key": n.node_key,
                    "title": n.title,
                    "prompt": n.prompt_override,
                    "max_retries": n.max_retries,
                }
                for n in new_nodes
            ],
            "edges": [{"from_node_key": e.from_node_key, "to_node_key": e.to_node_key, "edge_type": e.edge_type, "condition_expr": e.condition_expr} for e in new_edges],
        }, ensure_ascii=False, default=str)
        await self.store.save_workflow_graph(graph, nodes=new_nodes, edges=new_edges)

    async def _apply_pending_conductor_dispatches(
        self,
        graph: WorkflowGraph,
        issue: CodexIssue,
    ) -> set[str]:
        if not hasattr(self.store, "load_conductor_state") or not hasattr(self.store, "save_conductor_state"):
            return set()
        state = await self.store.load_conductor_state(issue.id)
        if state is None:
            return set()
        from app.application.conductor_actions import (
            decode_pending_dispatches,
            encode_pending_dispatches,
        )
        pending = decode_pending_dispatches(state)
        if not pending:
            return set()

        nodes_by_key = {node.node_key: node for node in graph.nodes}
        remaining: list[dict] = []
        priority_node_keys: set[str] = set()
        consumed = False
        for dispatch in pending:
            target_key = dispatch.get("target_node_key")
            target = nodes_by_key.get(target_key)
            if target is None:
                continue
            if target.status in {"running", "done", "failed", "skipped"}:
                continue

            action = dispatch.get("action")
            prompt_override = target.prompt_override
            if action == "inject_context":
                context = str(dispatch.get("context_message") or "").strip()
                if context:
                    prompt_override = self._prepend_conductor_context(
                        context,
                        target.prompt_override,
                        issue,
                    )
                    await self.store.update_workflow_node(target.id, prompt_override=prompt_override)
                    target.prompt_override = prompt_override
                    consumed = True
                else:
                    remaining.append(dispatch)
            elif action == "dispatch_next":
                replacement = dispatch.get("prompt_override")
                if replacement:
                    prompt_override = str(replacement)
                elif dispatch.get("context_inject"):
                    prompt_override = self._prepend_conductor_context(
                        str(dispatch["context_inject"]),
                        target.prompt_override,
                        issue,
                    )
                await self.store.update_workflow_node(
                    target.id,
                    status="ready",
                    prompt_override=prompt_override,
                )
                target.status = "ready"
                target.prompt_override = prompt_override
                priority_node_keys.add(target.node_key)
                consumed = True
            else:
                remaining.append(dispatch)

        if consumed:
            state.pending_dispatches_json = encode_pending_dispatches(remaining)
            state.updated_at = datetime.now()
            await self.store.save_conductor_state(state)
        return priority_node_keys

    @staticmethod
    def _prepend_conductor_context(
        context_message: str,
        existing_prompt: str | None,
        issue: CodexIssue,
    ) -> str:
        issue_body = (issue.description or "").strip()
        if issue.title and issue_body:
            fallback = f"{issue.title}\n\n{issue_body}"
        else:
            fallback = issue.title or issue_body or ""
        base = existing_prompt or fallback
        return f"[CONDUCTOR CONTEXT]\n{context_message.strip()}\n\n{base}".strip()

    async def _record_conductor_decision_state(
        self,
        *,
        issue: CodexIssue,
        task: CodexTask,
        node: WorkflowNode,
        decision: dict,
    ) -> None:
        if decision.get("_state_recorded"):
            return
        if not hasattr(self.store, "save_conductor_state"):
            return
        try:
            from app.application.conductor_actions import record_conductor_decision
            from app.domain.models import ConductorState
            state = None
            if hasattr(self.store, "load_conductor_state"):
                state = await self.store.load_conductor_state(issue.id)
            state = state or ConductorState(issue_id=issue.id)
            updated = record_conductor_decision(
                state,
                decision=decision,
                task_id=task.id,
                completed_node_key=node.node_key,
            )
            await self.store.save_conductor_state(updated)
        except Exception as exc:  # noqa: BLE001
            logger.debug("conductor scheduler state update failed: %s", exc)

    async def _build_conductor_spawn_diff(
        self,
        *,
        graph: WorkflowGraph,
        source_node: WorkflowNode,
        decision: dict,
    ) -> dict:
        action = decision.get("action")
        catalog = AgentCatalog()
        if action == "spawn_specialist":
            role_key = str(decision.get("role_key") or "").strip()
            if not role_key:
                raise WorkflowSchedulerError("spawn_specialist requires role_key")
            normalized = catalog.normalize_role_key(role_key)
            definition = catalog.resolve_agent(f"{SPECIALIST_PREFIX}{normalized}")
            agent = await self._ensure_catalog_agent(definition)
            base_node_key = f"specialist_{normalized}"
        elif action == "spawn_custom":
            name = str(decision.get("name") or decision.get("role_key") or "").strip()
            prompt = str(decision.get("prompt") or "").strip()
            if not name or not prompt:
                raise WorkflowSchedulerError("spawn_custom requires name and prompt")
            definition = catalog.register_custom(
                name=name,
                prompt=prompt,
                schema=decision.get("schema") if isinstance(decision.get("schema"), dict) else None,
            )
            agent = await self._ensure_catalog_agent(definition)
            base_node_key = definition.role_key.replace(":", "_")
        else:
            return {}

        prompt_override = str(decision.get("prompt") or definition.prompt_template).strip()
        existing_edges = {
            (edge.from_node_key, edge.to_node_key)
            for edge in graph.edges
        }
        for node in graph.nodes:
            if (
                node.agent_id == agent.id
                and node.prompt_override == prompt_override
                and (source_node.node_key, node.node_key) in existing_edges
            ):
                return {}

        node_key = self._unique_node_key(base_node_key, {node.node_key for node in graph.nodes})
        return {
            "added_nodes": [
                {
                    "node_key": node_key,
                    "agent_id": agent.id,
                    "title": decision.get("title") or agent.name,
                    "prompt": prompt_override,
                    "max_retries": definition.default_max_retries,
                }
            ],
            "added_edges": [
                {
                    "from_node_key": source_node.node_key,
                    "to_node_key": node_key,
                    "edge_type": "sequence",
                }
            ],
        }

    async def _ensure_catalog_agent(self, definition: AgentDefinition) -> Agent:
        if definition.role_key.startswith(CUSTOM_PREFIX):
            role_key = definition.role_key
            tier = "custom"
            artifact_role = definition.role_key
            system_prompt = definition.prompt_template
            is_builtin = False
        else:
            role_key = f"{SPECIALIST_PREFIX}{definition.role_key}"
            tier = "specialist"
            artifact_role = definition.role_key
            system_prompt = f"[specialist:{definition.role_key}]"
            is_builtin = True

        existing = await self.store.list_agents(workspace_id=None, role_key=role_key)
        if existing:
            return existing[0]

        now = datetime.now()
        agent = Agent(
            id=f"agent-{role_key.replace(':', '-')}",
            workspace_id=None,
            name=definition.display_name,
            role_key=role_key,
            description=definition.prompt_template,
            system_prompt_template=system_prompt,
            output_schema=definition.output_schema,
            default_executor="claude",
            artifact_subdir=f"specialists/{artifact_role}",
            persist_kind="specialist",
            agent_tier=tier,
            is_builtin=is_builtin,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_agent(agent)
        return agent

    @staticmethod
    def _unique_node_key(base: str, existing: set[str]) -> str:
        if base not in existing:
            return base
        index = 1
        while f"{base}_{index}" in existing:
            index += 1
        return f"{base}_{index}"

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
        # `[builtin:<role>]` is a placeholder telling the runtime to defer to
        # RoleWorkflowService — but downstream prompt builders use
        # `task.prompt` as the *user_requirement* line. Substitute the real
        # issue title + description so PM/Architect/Engineer/QA see actual
        # context, not the literal `[builtin:engineer]` string.
        if isinstance(prompt, str) and prompt.startswith("[builtin:"):
            issue_body = (issue.description or "").strip()
            if issue.title and issue_body:
                prompt = f"{issue.title}\n\n{issue_body}"
            else:
                prompt = issue.title or issue_body or prompt

        # Engineer rework: when this is a retry caused by an upstream QA
        # failure, surface the most recent QA report on disk as feedback so
        # the engineer prompt builder includes it under "REWORK REQUIRED".
        # Fallback: when QA didn't fail (e.g. human rejected a passing run),
        # use issue.review_comment so the user's note still reaches engineer.
        # Also covers multi-instance engineer nodes like `engineer#0`, `engineer#1`
        # and Phase-1 parallel roles like `engineer_frontend`, `engineer_backend`.
        is_engineer_role = agent.role_key == "engineer" or node.node_key.startswith("engineer")
        review_comment = None
        if is_engineer_role and node.retries > 0 and issue.git_worktree_path:
            review_comment = self._read_latest_qa_failure_summary(
                issue.git_worktree_path, issue.id
            )
            if not review_comment and getattr(issue, "review_comment", None):
                review_comment = issue.review_comment
        if agent.role_key == "architect" and getattr(issue, "review_comment", None):
            review_comment = issue.review_comment

        # Inherit worktree/git state from the issue so the runner can locate
        # artifacts. Falls back to None when the issue has no worktree yet
        # (tests, ephemeral issues) — the runner should tolerate that.
        # Built-in role workflows treat `task.title` as the user-facing issue
        # title (it ends up in PRD `issue_title` and engineer `issue_title`
        # fields). When the node title is a generic role tag, prefer the
        # actual issue title so artifacts capture the real intent.
        managed_role = agent.role_key in {"product_manager", "architect", "engineer", "qa"}
        effective_title = (
            issue.title
            if (managed_role and issue.title)
            else (node.title or agent.name)
        )

        # For multi-instance same-role nodes (e.g. engineer#0, engineer#1) and
        # Phase-1 parallel roles (engineer_frontend, engineer_backend), use the
        # node_key as task.role so artifact subdirectory isolation works
        # automatically — EngineerWorkflow uses role.startswith("engineer") to
        # determine the subdir, and the node_key encodes the instance identity.
        # Single-role nodes keep the canonical agent.role_key for back-compat.
        effective_role = (
            node.node_key
            if (node.node_key != agent.role_key and node.node_key.startswith(agent.role_key))
            else agent.role_key
        )

        # Phase 4: multi-instance engineer nodes carry a subtask scope in their
        # title (set by the orchestrator from subtask_split). Prepend the scope
        # to the prompt so the engineer knows which workstream to tackle.
        if "#" in node.node_key and is_engineer_role and node.title and node.title not in (prompt or ""):
            scope_prefix = f"[SUBTASK SCOPE: {node.title}]\n\n"
            prompt = scope_prefix + (prompt or "")

        task = CodexTask(
            id=str(uuid4()),
            session_id=issue.session_id,
            project_id=issue.project_id,
            issue_id=issue.id,
            phase=agent.role_key,  # Free-form tag now; kept for backward compat with old kanban
            title=effective_title,
            prompt=prompt,
            role=effective_role,
            executor=agent.default_executor or "codex",
            provider=agent.default_provider,
            model=agent.default_model,
            status="pending",
            workspace_path=issue.git_worktree_path,
            git_branch=issue.git_branch,
            git_base_branch=issue.git_base_branch,
            git_worktree_path=issue.git_worktree_path,
            workflow_node_id=node.id,
            review_comment=review_comment,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await self.store.save_codex_task(task)
        # Broadcast the new task to connected clients so the RunDetail / task
        # list updates immediately on stage transitions (e.g. architect→engineer).
        # Without this, the frontend only learns about the task when the runner
        # finally pushes a task_status patch and forces a manual refresh.
        if self._event_bus is not None:
            try:
                from app.application.task_serialization import serialize_task_payload
                await self._event_bus.append({
                    "type": "task_created",
                    "task": serialize_task_payload(task),
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to emit task_created for workflow node %s: %s",
                    node.node_key,
                    exc,
                )
        if agent.role_key == "architect" and getattr(issue, "review_comment", None):
            issue.review_comment = None
            issue.updated_at = datetime.now()
            await self.store.save_codex_issue(issue)
        await self.store.update_workflow_node(
            node.id,
            status="running",
            task_id=task.id,
            started_at=datetime.now(),
        )
        node.status = "running"
        node.task_id = task.id
        await self._emit_node_event(node, issue)
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

    def _read_latest_qa_failure_summary(
        self, workspace_path: str, issue_id: str
    ) -> str | None:
        """Return a short summary of the QA report on disk if it indicates a
        failure, formatted as actionable feedback for the engineer."""
        try:
            from pathlib import Path
            qa_plan_path = Path(workspace_path) / "issues" / issue_id / "qa" / "qa_plan.json"
            qa_report_path = Path(workspace_path) / "issues" / issue_id / "qa" / "qa_report.md"
            if not qa_plan_path.exists():
                return None
            plan = json.loads(qa_plan_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to read QA artifacts for rework feedback: %s", exc)
            return None

        status = plan.get("status", "unknown")
        if status not in {"failed", "needs_follow_up"}:
            # Engineer is being re-fired but QA didn't actually fail —
            # nothing useful to feed forward.
            return None

        bugs = plan.get("bugs_found") or []
        gaps = plan.get("test_gaps") or []
        risks = plan.get("risks") or []
        commands = plan.get("commands_run") or []
        recommendation = plan.get("final_recommendation") or ""

        def bullets(items):
            return [f"  - {x}" for x in items] if items else ["  (none reported)"]

        lines = [
            f"QA marked the previous engineer pass as **{status}**. You must address each item below before the next QA run.",
            "",
        ]
        if recommendation:
            lines.extend([f"Final recommendation: {recommendation}", ""])
        lines.append("Bugs found:")
        lines.extend(bullets(bugs))
        lines.extend(["", "Test gaps / framework notes:"])
        lines.extend(bullets(gaps))
        lines.extend(["", "Risks:"])
        lines.extend(bullets(risks))
        lines.extend(["", "Commands actually run by QA (with exit codes):"])
        lines.extend(bullets(commands))
        if qa_report_path.exists():
            lines.extend([
                "",
                f"Full QA report on disk: {qa_report_path.relative_to(workspace_path)}",
            ])
        return "\n".join(line for line in lines if line is not None)

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
        previous_status = latest.status
        terminal_now = False
        new_issue_status: str | None = None
        if statuses and statuses <= {"done", "skipped"}:
            if latest.status != "done":
                latest.status = "done"
                await self.store.save_workflow_graph(latest)
                terminal_now = True
            new_issue_status = "completed"
        elif "failed" in statuses and not any(s in {"pending", "blocked", "ready", "running"} for s in statuses):
            if latest.status != "failed":
                latest.status = "failed"
                await self.store.save_workflow_graph(latest)
                terminal_now = True
            new_issue_status = "failed"

        # Sync the issue's top-level status with the graph terminal state so
        # the issue list chip flips from "排队中"/"运行中" to "完成"/"失败"
        # once all nodes settle. Without this, the issue stays at the last
        # transient status (e.g. "open" → 排队中) even though the work is done.
        if new_issue_status is not None:
            issue = await self.store.load_codex_issue(latest.issue_id)
            if issue is not None and issue.status != new_issue_status:
                # Never overwrite an in-flight human gate — those resolve via
                # explicit endpoints (approve-plan, qa-review), not the scheduler.
                # awaiting_merge is also a terminal-ish state the user moves out
                # of by clicking Merge Back.
                if issue.status not in {"awaiting_approval", "awaiting_review", "awaiting_merge"}:
                    issue.status = new_issue_status
                    issue.updated_at = datetime.now()
                    await self.store.save_codex_issue(issue)
                    if self._event_bus is not None:
                        try:
                            await self._event_bus.append({
                                "type": "issue_updated",
                                "issue_id": issue.id,
                                "session_id": issue.session_id,
                                "status": issue.status,
                            })
                        except Exception:  # noqa: BLE001
                            pass

        # Auto-advance the issue's `current_phase` when all nodes whose
        # agent role matches a known phase have completed. This keeps the
        # issue header's phase chip in sync with the DAG progress without
        # the UI having to know the role→phase mapping.
        await self._maybe_advance_phase(latest)

        # Sink lessons into the project's team_notes.md the FIRST time the
        # graph lands terminal. Best-effort — never blocks the graph.
        if terminal_now and previous_status not in {"done", "failed"}:
            await self._record_project_memory(latest)

    async def _record_project_memory(self, graph: WorkflowGraph) -> None:
        try:
            from app.application.project_memory_service import project_memory
            issue = await self.store.load_codex_issue(graph.issue_id)
            if issue is None:
                return
            project_repo_path = None
            if issue.project_id:
                load_project = getattr(self.store, "load_project", None)
                if callable(load_project):
                    proj = await load_project(issue.project_id)
                    if proj is not None:
                        project_repo_path = proj.repo_path
            project_memory.record_issue_completion(
                project_repo_path,
                issue_id=issue.id,
                issue_title=issue.title or issue.id,
                worktree_path=issue.git_worktree_path,
                graph_status=graph.status,
            )
            # Knowledge stack: rebuild team_notes_state for this project so
            # newly-appended blocks become visible in the Team Notes UI and
            # any orphaned state rows are pruned.
            try:
                from app.application.team_notes_service import team_notes
                if issue.project_id and project_repo_path:
                    md = team_notes.read_markdown(project_repo_path)
                    parsed = team_notes.parse_blocks(md)
                    state = await team_notes._load_state(self.store, issue.project_id)
                    parsed_ids = {b.block_id for b in parsed}
                    # Ensure every parsed block has a row (default: not deleted, not pinned)
                    for b in parsed:
                        if b.block_id not in state:
                            await team_notes._upsert_state(
                                self.store, issue.project_id, b.block_id,
                            )
                    # Drop state rows whose block no longer exists on disk
                    for stale_id in set(state.keys()) - parsed_ids:
                        try:
                            conn = await self.store._get_conn()
                            await conn.execute(
                                "DELETE FROM team_notes_state WHERE project_id = ? AND block_id = ?",
                                (issue.project_id, stale_id),
                            )
                            await conn.commit()
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("team_notes_state reconcile skipped: %s", exc)
            # S3c: auto-distill team_notes.md once it accumulates past
            # DISTILL_TRIGGER_BLOCKS raw issue entries. Reuses the
            # orchestrator LLM runner so we share the runtime catalog
            # config. Best-effort — distillation failures are silent.
            try:
                import os
                if os.getenv("WORKFLOW_ORCHESTRATOR_LLM", "").lower() != "false":
                    from app.application.llm_runner import build_llm_runner
                    from app.bootstrap import codex_store as _store  # local import to avoid cycles
                    catalog_service = None
                    try:
                        from app.bootstrap import (
                            get_runtime_catalog_service as _get_catalog_service,
                        )
                        catalog_service = _get_catalog_service()
                    except (ImportError, AttributeError):
                        # Older bootstrap shape — try the api layer's resolver.
                        try:
                            from app.interfaces.api import _get_runtime_catalog_service as _api_get
                            catalog_service = _api_get()
                        except Exception:  # noqa: BLE001
                            catalog_service = None
                    if catalog_service is not None:
                        runner = build_llm_runner(catalog_service)
                        await project_memory.maybe_distill(project_repo_path, runner)
            except Exception as exc:  # noqa: BLE001
                logger.debug("project memory distill skipped: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("project memory append failed for graph %s: %s", graph.id, exc)

    # Role → phase the issue advances *into* once every node of that role
    # completes successfully. E.g. once all `product_manager` nodes are done,
    # we transition the issue into the `architecture` phase.
    _ROLE_TO_NEXT_PHASE = {
        "product_manager": "architecture",
        "architect": "development",
        "engineer": "testing",
        "qa": "done",
    }

    async def _maybe_advance_phase(self, graph: WorkflowGraph) -> None:
        if graph is None:
            return
        issue = await self.store.load_codex_issue(graph.issue_id)
        if issue is None:
            return
        agents_by_id = {a.id: a for a in await self.store.list_agents(workspace_id=None)}
        # Group nodes by role.
        from collections import defaultdict
        statuses_by_role: dict[str, set[str]] = defaultdict(set)
        for node in graph.nodes:
            agent = agents_by_id.get(node.agent_id)
            role = (agent.role_key if agent else None) or node.node_key
            statuses_by_role[role].add(node.status)
        # Walk roles in the canonical order and pick the *latest* fully-
        # completed role's next phase as the target. This handles non-linear
        # DAGs (e.g. multiple architects) and ensures we only step forward.
        target_phase = None
        for role in ("product_manager", "architect", "engineer", "qa"):
            statuses = statuses_by_role.get(role)
            if statuses and statuses <= {"done", "skipped"}:
                target_phase = self._ROLE_TO_NEXT_PHASE.get(role)
        if target_phase is None or target_phase == issue.current_phase:
            return
        # Only step forward in the canonical phase order; never regress.
        order = ["requirements", "architecture", "development", "testing", "done"]
        try:
            cur_idx = order.index(issue.current_phase or "requirements")
            tgt_idx = order.index(target_phase)
        except ValueError:
            return
        if tgt_idx <= cur_idx:
            return
        issue.current_phase = target_phase
        issue.updated_at = datetime.now()
        await self.store.save_codex_issue(issue)
        if self._event_bus is not None:
            try:
                await self._event_bus.append({
                    "type": "issue_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "current_phase": issue.current_phase,
                })
            except Exception:  # noqa: BLE001
                pass


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
