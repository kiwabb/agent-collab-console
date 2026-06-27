from __future__ import annotations

"""Phase 4: Specialist Orchestrator — P2P mesh calls between agents.

Allows Engineer/QA to directly invoke specialist agents (security_reviewer, etc.)
without waiting for the Conductor. Reuses the parent-pause / child-run / parent-resume
pattern from HelpOrchestrator.

Core flows:
  1. Engineer/QA JSON output includes `call_specialist: {role_key, prompt, why}`
  2. RoleWorkflowService.persist_result() detects it → calls SpecialistOrchestrator.request_specialist()
  3. Parent task enters `waiting_for_specialist` state
  4. Specialist child task runs independently
  5. workflow_scheduler.on_task_completed() detects specialist child completion
  6. Specialist's SubAgentResult written to parent.review_comment
  7. Parent task reset to pending, re-dispatched with specialist findings

Mesh depth limit: ≤ 2 (no specialist→specialist calls).
"""
from datetime import datetime  # noqa: E402, I001
from uuid import uuid4  # noqa: E402

from app.domain.models import CodexTask, AgentMessage  # noqa: E402


class SpecialistOrchestratorError(ValueError):
    pass


class SpecialistOrchestrator:
    def __init__(self, store, event_bus, task_runner):
        self.store = store
        self.event_bus = event_bus
        self.task_runner = task_runner

    async def request_specialist(
        self,
        *,
        parent_task,
        specialist_role_key: str,
        specialist_prompt: str,
        why: str = "",
    ):
        """
        Pause the parent task and spawn a specialist child task.

        Args:
            parent_task: The running Engineer/QA CodexTask requesting help
            specialist_role_key: e.g., "specialist:security_reviewer"
            specialist_prompt: The question/request for the specialist
            why: Brief reason why specialist is needed (for logging)

        Returns:
            The created specialist child task

        Raises:
            SpecialistOrchestratorError if preconditions fail (mesh depth, unresolved requests, etc.)
        """
        # Validate parent task can make specialist calls
        if parent_task.status not in {"running", "responding"}:
            raise SpecialistOrchestratorError(
                f"Parent task {parent_task.id} must be running to request specialist (current status: {parent_task.status})"
            )
        if parent_task.task_kind == "specialist_child":
            raise SpecialistOrchestratorError(
                "Specialist child tasks cannot request further specialist calls (mesh depth ≤ 2)"
            )
        if await self._has_unresolved_specialist_request(parent_task.id):
            raise SpecialistOrchestratorError(
                f"Parent task {parent_task.id} already has an unresolved specialist request"
            )

        # Validate specialist role exists in catalog
        if not specialist_role_key or not specialist_role_key.startswith("specialist:"):
            raise SpecialistOrchestratorError(
                f"Invalid specialist role key: {specialist_role_key} (must start with 'specialist:')"
            )

        # Create specialist child task
        child_id = str(uuid4())
        now = datetime.now()

        # Determine executor for specialist: default to "claude" for now,
        # could be configurable per specialist in future.
        specialist_executor = "claude"

        child = CodexTask(
            id=child_id,
            session_id=parent_task.session_id,
            project_id=parent_task.project_id,
            issue_id=parent_task.issue_id,
            title=f"[Specialist] {specialist_role_key}",
            prompt=specialist_prompt,
            role=specialist_role_key,
            executor=specialist_executor,
            status="pending",
            result=None,
            parent_task_id=parent_task.id,
            task_kind="specialist_child",
            workspace_path=parent_task.workspace_path,
            git_worktree_path=parent_task.git_worktree_path,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_codex_task(child)

        # Pause parent task
        parent_task.status = "waiting_for_specialist"
        parent_task.updated_at = now
        await self.store.save_codex_task(parent_task)

        # If parent has an active execution process, mark it complete
        if parent_task.last_execution_process_id:
            await self.store.update_execution_process_status(
                parent_task.last_execution_process_id,
                "Completed",
                completed_at=now,
            )

        # Record specialist call as AgentMessage for the feed
        try:
            graph = await self.store.load_workflow_graph_for_issue(parent_task.issue_id)
            msg = AgentMessage(
                id=str(uuid4()),
                issue_id=parent_task.issue_id,
                graph_id=graph.id if graph else "",
                from_node_key=parent_task.role,  # Engineer or QA
                to_node_key=specialist_role_key,
                message_type="specialist_call",
                body=f"Calling {specialist_role_key}:\n\n{specialist_prompt}\n\n**Why**: {why}",
                created_at=now,
            )
            await self.store.save_agent_message(msg)
        except Exception:  # noqa: BLE001, RUF100
            pass  # AgentMessage is nice-to-have, don't block on failure

        # Emit events for real-time UI updates
        await self.event_bus.append(
            {
                "type": "specialist_requested",
                "parent_task_id": parent_task.id,
                "child_task_id": child_id,
                "specialist_role": specialist_role_key,
                "reason": why,
            }
        )
        await self.event_bus.append(
            {
                "type": "task_status",
                "task_id": parent_task.id,
                "issue_id": parent_task.issue_id,
                "session_id": parent_task.session_id,
                "status": parent_task.status,
            }
        )

        # Start the specialist child task
        await self.task_runner.start_task_run(child)

        await self.event_bus.append(
            {
                "type": "specialist_child_started",
                "parent_task_id": parent_task.id,
                "child_task_id": child_id,
                "specialist_role": specialist_role_key,
            }
        )

        return child

    async def complete_specialist_request(
        self,
        specialist_child_task_id: str,
        specialist_result_summary: str,
    ) -> CodexTask:
        """
        Complete a specialist child task and resume the parent.

        Called by workflow_scheduler.on_task_completed() after a specialist_child finishes.

        Args:
            specialist_child_task_id: The specialist child task that completed
            specialist_result_summary: Structured summary from SubAgentResult to inject into parent

        Returns:
            The parent task with status reset to pending (ready to re-run)

        Raises:
            SpecialistOrchestratorError if parent cannot be found or resumed
        """
        child = await self.store.load_codex_task(specialist_child_task_id)
        if child is None:
            raise SpecialistOrchestratorError(
                f"Specialist child task {specialist_child_task_id} not found"
            )

        parent = await self.store.load_codex_task(child.parent_task_id)
        if parent is None:
            raise SpecialistOrchestratorError(f"Parent task {child.parent_task_id} not found")

        now = datetime.now()

        # Inject specialist result into parent's review_comment for the continuation prompt
        specialist_continuation = (
            f"[SPECIALIST RESULT from {child.role}]\n\n{specialist_result_summary}\n\n"
            f"Review the above specialist findings and incorporate them into your next output."
        )
        if parent.review_comment:
            parent.review_comment = parent.review_comment + "\n\n" + specialist_continuation
        else:
            parent.review_comment = specialist_continuation

        # Reset parent to pending so it can resume with specialist findings
        parent.status = "pending"
        parent.updated_at = now
        await self.store.save_codex_task(parent)

        # Record specialist result as AgentMessage for the feed
        try:
            graph = await self.store.load_workflow_graph_for_issue(parent.issue_id)
            msg = AgentMessage(
                id=str(uuid4()),
                issue_id=parent.issue_id,
                graph_id=graph.id if graph else "",
                from_node_key=child.role,  # specialist
                to_node_key=parent.role,  # engineer or qa
                message_type="specialist_result",
                body=specialist_result_summary[:500],  # Truncate for feed display
                created_at=now,
            )
            await self.store.save_agent_message(msg)
        except Exception:  # noqa: BLE001, RUF100
            pass

        # Emit events
        await self.event_bus.append(
            {
                "type": "specialist_completed",
                "parent_task_id": parent.id,
                "child_task_id": specialist_child_task_id,
                "specialist_role": child.role,
            }
        )
        await self.event_bus.append(
            {
                "type": "task_status",
                "task_id": parent.id,
                "issue_id": parent.issue_id,
                "session_id": parent.session_id,
                "status": parent.status,
            }
        )

        return parent

    async def _has_unresolved_specialist_request(self, parent_task_id: str) -> bool:
        """Check if parent has any pending specialist_child tasks."""
        try:
            children = await self.store.list_codex_tasks(parent_task_id=parent_task_id)
            return any(
                c.task_kind == "specialist_child"
                and c.status in {"pending", "running", "responding"}
                for c in children
            )
        except Exception:  # noqa: BLE001, RUF100
            return False
