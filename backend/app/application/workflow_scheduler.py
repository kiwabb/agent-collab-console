"""Task completion hook for Conductor-driven orchestration.

In the Conductor world, the WorkflowScheduler is no longer a scheduler — it
exists only to react to task completion events:

  1. Mirror the task's terminal status onto its WorkflowNode
  2. Emit `workflow_node_updated` so the frontend graph refreshes
  3. Signal TaskCompletionRegistry so the Conductor's awaiting
     `dispatch_subagent` tool call can unblock with a SubAgentResult
  4. Phase 4 only: when a specialist_child finishes, fold its findings into
     the parent task's review_comment and re-dispatch the parent node
  5. Best-effort: advance the issue's `current_phase` label for the UI

It does NOT mark the WorkflowGraph terminal — `run_issue_conductor_loop`
owns the graph lifecycle and sets `graph.status` itself when the Conductor
loop exits.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from app.domain.models import (
    Agent,
    AgentMessage,
    CodexIssue,
    CodexTask,
    WorkflowGraph,
    WorkflowNode,
)

logger = logging.getLogger(__name__)


class WorkflowSchedulerError(RuntimeError):
    pass


class WorkflowScheduler:
    """Task-completion hook owner.

    The name is historical; in Conductor mode this class does not schedule
    anything. It is constructed cheaply and only `on_task_completed` runs.
    """

    def __init__(self, store, task_dispatcher=None, event_bus=None) -> None:
        self.store = store
        self._task_dispatcher = task_dispatcher  # callable(task) -> awaitable, optional
        self._event_bus = event_bus

    async def _emit_node_event(self, node: WorkflowNode, issue: CodexIssue | None) -> None:
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

    async def _emit_artifact_validation_failed(
        self,
        task: CodexTask,
        node: WorkflowNode,
        issue: CodexIssue | None,
        validation_error: dict,
    ) -> None:
        """GAP E/J: structured signal that a subagent's artifact failed schema
        validation, so the UI can flag it and the Conductor's re-dispatch is
        observable. Best-effort — never let observability break the hook."""
        if self._event_bus is None:
            return
        try:
            await self._event_bus.append({
                "type": "artifact_validation_failed",
                "issue_id": issue.id if issue is not None else task.issue_id,
                "session_id": issue.session_id if issue is not None else None,
                "task_id": task.id,
                "node_id": node.id,
                "node_key": node.node_key,
                "role": task.role,
                "validation_error": validation_error,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("artifact_validation_failed emit failed: %s", exc)

    async def on_task_completed(self, task: CodexTask) -> None:
        """Hook called by the task runner once a task ends."""
        if not getattr(task, "workflow_node_id", None):
            return
        node = await self.store.find_node_by_task_id(task.id)
        if node is None:
            return
        terminal = self._task_status_to_node_status(task.status)
        if terminal is None:
            return
        graph = await self.store.load_workflow_graph(node.graph_id)
        issue_for_event = None
        if graph is not None:
            try:
                issue_for_event = await self.store.load_codex_issue(graph.issue_id)
            except Exception:  # noqa: BLE001
                issue_for_event = None
            if terminal == "failed" and await self._maybe_auto_retry_failed_node(
                task,
                node,
                graph,
                issue_for_event,
            ):
                return
        await self.store.update_workflow_node(
            node.id,
            status=terminal,
            task_id=node.task_id,
            completed_at=datetime.now(),
        )
        node.status = terminal
        if graph is None:
            return

        await self._emit_node_event(node, issue_for_event)

        # Signal TaskCompletionRegistry so Conductor's dispatch_subagent
        # tool call can unblock with a SubAgentResult.
        from app.application.task_completion_registry import TaskCompletionRegistry
        reg = TaskCompletionRegistry.get()
        if reg.is_registered(task.id):
            from app.application.subagent_result_builder import build_subagent_result
            try:
                subagent_result = build_subagent_result(
                    task=task,
                    node=node,
                    doc=getattr(task, "_subagent_doc", None),
                )
                # GAP E: if artifact persistence failed schema validation, the task
                # is `done` but its structured artifact is missing/malformed. Tell
                # the Conductor explicitly (status=artifact_invalid) so it can
                # re-dispatch with a corrective prompt instead of proceeding on a
                # silent empty handoff. Surface a structured event for observability.
                validation_error = getattr(task, "_validation_error", None)
                signal_payload = {
                    "task_id": task.id,
                    "role": task.role,
                    "status": "artifact_invalid" if validation_error else task.status,
                    "summary": subagent_result.summary,
                    "artifact_json": subagent_result.artifact_json,
                    "files_changed": subagent_result.files_changed,
                    "qa_commands": subagent_result.qa_commands,
                    "clarification_question": subagent_result.clarification_question,
                }
                if validation_error:
                    signal_payload["validation_error"] = validation_error
                    await self._emit_artifact_validation_failed(
                        task, node, issue_for_event, validation_error
                    )
                reg.signal(task.id, signal_payload)
            except Exception:  # noqa: BLE001
                reg.signal(task.id, {
                    "task_id": task.id,
                    "role": task.role,
                    "status": task.status,
                    "summary": task.result or "",
                })

        # Phase 4: specialist_child → resume parent with findings.
        if task.task_kind == "specialist_child" and task.status == "done":
            if await self._maybe_resume_from_specialist(task, graph):
                return

        # Keep the issue's `current_phase` label in step with completed roles.
        await self._maybe_advance_phase(graph)

    async def _maybe_auto_retry_failed_node(
        self,
        task: CodexTask,
        node: WorkflowNode,
        graph: WorkflowGraph,
        issue: CodexIssue | None,
    ) -> bool:
        if self._task_dispatcher is None or issue is None:
            return False
        if node.retries >= node.max_retries:
            return False

        now = datetime.now()
        retry_number = node.retries + 1
        retry_task = CodexTask(
            id=str(uuid4()),
            session_id=task.session_id,
            project_id=task.project_id,
            issue_id=task.issue_id,
            phase=task.phase,
            title=task.title,
            prompt=task.prompt,
            role=task.role,
            executor=task.executor,
            provider=task.provider,
            model=task.model,
            status="pending",
            parent_task_id=task.id,
            task_kind=task.task_kind,
            workspace_path=task.workspace_path,
            git_branch=task.git_branch,
            git_base_branch=task.git_base_branch,
            git_worktree_path=task.git_worktree_path,
            review_comment=self._auto_retry_review_comment(task, retry_number, node.max_retries),
            workflow_node_id=node.id,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_codex_task(retry_task)
        await self.store.update_workflow_node(
            node.id,
            status="running",
            task_id=retry_task.id,
            retries=retry_number,
            started_at=now,
            completed_at=None,
        )
        await self._emit_retry_event(
            task=task,
            retry_task=retry_task,
            node=node,
            issue=issue,
            retry_number=retry_number,
            max_retries=node.max_retries,
        )
        try:
            result = self._task_dispatcher(retry_task)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001 - retry dispatch is best-effort recovery.
            logger.warning(
                "workflow node auto-retry dispatch failed issue_id=%s node_id=%s task_id=%s: %s",
                graph.issue_id,
                node.id,
                retry_task.id,
                exc,
            )
            retry_task.status = "failed"
            retry_task.result = f"Auto retry dispatch failed: {exc}"
            retry_task.updated_at = datetime.now()
            await self.store.save_codex_task(retry_task)
            node.task_id = task.id
            await self._emit_retry_failed_event(node, issue, retry_task, exc)
            return False
        return True

    @staticmethod
    def _auto_retry_review_comment(task: CodexTask, retry_number: int, max_retries: int) -> str:
        parts = [
            f"[AUTO RETRY {retry_number}/{max_retries}] The previous attempt failed. "
            "Retry the same workflow node and address the failure before continuing.",
        ]
        if task.review_comment:
            parts.append(f"Previous review context:\n{task.review_comment.strip()}")
        if task.result:
            result = task.result.strip()
            if len(result) > 1000:
                result = result[:1000] + "\n... (truncated)"
            parts.append(f"Previous failure result:\n{result}")
        return "\n\n".join(parts)

    async def _emit_retry_event(
        self,
        *,
        task: CodexTask,
        retry_task: CodexTask,
        node: WorkflowNode,
        issue: CodexIssue,
        retry_number: int,
        max_retries: int,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.append({
                "type": "workflow_node_retrying",
                "issue_id": issue.id,
                "session_id": issue.session_id,
                "node_id": node.id,
                "node_key": node.node_key,
                "previous_task_id": task.id,
                "retry_task_id": retry_task.id,
                "retry": retry_number,
                "max_retries": max_retries,
            })
            await self._event_bus.append({
                "type": "task_status",
                "task_id": retry_task.id,
                "issue_id": retry_task.issue_id,
                "session_id": retry_task.session_id,
                "status": retry_task.status,
                "review_comment": retry_task.review_comment,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("workflow_node_retrying emit failed: %s", exc)

    async def _emit_retry_failed_event(
        self,
        node: WorkflowNode,
        issue: CodexIssue,
        retry_task: CodexTask,
        exc: Exception,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.append({
                "type": "workflow_node_retry_failed",
                "issue_id": issue.id,
                "session_id": issue.session_id,
                "node_id": node.id,
                "node_key": node.node_key,
                "retry_task_id": retry_task.id,
                "status": "failed",
                "error": str(exc),
            })
            await self._event_bus.append({
                "type": "task_status",
                "task_id": retry_task.id,
                "issue_id": retry_task.issue_id,
                "session_id": retry_task.session_id,
                "status": retry_task.status,
                "review_comment": retry_task.review_comment,
            })
        except Exception as emit_exc:  # noqa: BLE001
            logger.debug("workflow_node_retry_failed emit failed: %s", emit_exc)

    async def _maybe_resume_from_specialist(
        self, specialist_child_task: CodexTask, graph: WorkflowGraph
    ) -> bool:
        """Phase 4: inject specialist findings into the parent task's
        review_comment and create a fresh parent task to re-run with them.
        Returns True if the parent was resumed."""
        parent = await self.store.load_codex_task(specialist_child_task.parent_task_id)
        if parent is None:
            logger.warning("Specialist child %s has no parent task", specialist_child_task.id)
            return False

        now = datetime.now()
        specialist_summary = specialist_child_task.result or "(no result)"
        if len(specialist_summary) > 1000:
            specialist_summary = specialist_summary[:1000] + "\n... (truncated)"

        continuation = (
            f"[SPECIALIST RESULT from {specialist_child_task.role}]\n\n"
            f"{specialist_summary}\n\n"
            f"Incorporate the above specialist findings into your next output."
        )
        parent.review_comment = (
            f"{parent.review_comment}\n\n{continuation}"
            if parent.review_comment
            else continuation
        )
        parent.status = "pending"
        parent.updated_at = now
        await self.store.save_codex_task(parent)

        try:
            msg = AgentMessage(
                id=str(uuid4()),
                issue_id=parent.issue_id,
                graph_id=graph.id if graph else "",
                from_node_key=specialist_child_task.role,
                to_node_key=parent.role,
                message_type="specialist_result",
                body=specialist_summary[:500],
                created_at=now,
            )
            await self.store.save_agent_message(msg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to record specialist result message: %s", exc)

        if self._event_bus is not None:
            try:
                await self._event_bus.append({
                    "type": "specialist_completed",
                    "parent_task_id": parent.id,
                    "child_task_id": specialist_child_task.id,
                    "specialist_role": specialist_child_task.role,
                })
                await self._event_bus.append({
                    "type": "task_status",
                    "task_id": parent.id,
                    "issue_id": parent.issue_id,
                    "session_id": parent.session_id,
                    "status": parent.status,
                })
            except Exception:  # noqa: BLE001
                pass

        # Re-dispatch the parent's role on a fresh task so the runner picks
        # up the updated review_comment via the REWORK branch.
        try:
            parent_issue = await self.store.load_codex_issue(parent.issue_id)
            if parent_issue is None:
                return True
            from app.application.task_dispatcher import dispatch_role
            await dispatch_role(
                issue=parent_issue,
                role=parent.role,
                store=self.store,
                task_dispatcher_fn=self._task_dispatcher,
                event_bus=self._event_bus,
                prev_node_key=specialist_child_task.role,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to re-dispatch parent after specialist: %s", exc)

        return True

    @staticmethod
    def _task_status_to_node_status(task_status: str) -> str | None:
        if task_status == "done":
            return "done"
        if task_status in {"failed", "error"}:
            return "failed"
        return None

    # role → phase the issue moves *into* once every node of that role lands
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
        from collections import defaultdict
        statuses_by_role: dict[str, set[str]] = defaultdict(set)
        for node in graph.nodes:
            agent = agents_by_id.get(node.agent_id)
            role = (agent.role_key if agent else None) or node.node_key
            statuses_by_role[role].add(node.status)
        target_phase = None
        for role in ("product_manager", "architect", "engineer", "qa"):
            statuses = statuses_by_role.get(role)
            if statuses and statuses <= {"done", "skipped"}:
                target_phase = self._ROLE_TO_NEXT_PHASE.get(role)
        if target_phase is None or target_phase == issue.current_phase:
            return
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
