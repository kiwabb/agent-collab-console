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

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import datetime
from typing import NoReturn, Protocol, cast
from uuid import uuid4

from app.application.budget_service import (
    BudgetExecutionProcess,
    BudgetStore,
    compute_issue_budget_status,
)
from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.task_status_events import build_task_status_event
from app.application.task_statuses import (
    is_task_active_status,
    is_task_failure_status,
    is_task_pending_status,
    is_task_success_status,
    is_task_terminal_status,
    is_task_waiting_for_specialist_status,
)
from app.domain.models import AgentMessage, CodexIssue, CodexTask

logger = logging.getLogger(__name__)
_SPECIALIST_ROLE_SLOTS_BY_CHILD: dict[str, str] = {}


class SpecialistOrchestratorError(ValueError):
    pass


class SpecialistGovernanceError(SpecialistOrchestratorError):
    def __init__(self, message: str, *, gate: str, detail: str) -> None:
        super().__init__(message)
        self.gate = gate
        self.detail = detail


class SpecialistGraphRef(Protocol):
    id: str


class SpecialistStore(BudgetStore, Protocol):
    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...

    async def save_codex_task(self, task: CodexTask) -> None: ...

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None: ...

    async def list_execution_processes(
        self, session_id: str | None = None, task_id: str | None = None
    ) -> list[BudgetExecutionProcess]: ...

    async def load_workflow_graph_for_issue(self, issue_id: str) -> SpecialistGraphRef | None: ...

    async def save_agent_message(self, msg: AgentMessage) -> None: ...

    async def update_execution_process_status(
        self, proc_id: str, status: str, completed_at: datetime | None = None
    ) -> None: ...


class SpecialistEventBus(Protocol):
    async def append(self, event: dict[str, object]) -> None: ...


class SpecialistTaskRunner(Protocol):
    async def start_task_run(self, task: CodexTask) -> object: ...


class ListCodexTasksFn(Protocol):
    def __call__(self, *, parent_task_id: str | None = None) -> Awaitable[list[CodexTask]]: ...


def _specialist_blocker_id(child_task_id: str) -> str:
    return f"specialist:{child_task_id}"


class SpecialistOrchestrator:
    def __init__(
        self,
        store: SpecialistStore,
        event_bus: SpecialistEventBus,
        task_runner: SpecialistTaskRunner,
    ) -> None:
        self.store = store
        self.event_bus = event_bus
        self.task_runner = task_runner

    async def _raise_governance_failure(self, *, gate: str, exc: Exception) -> NoReturn:
        detail = f"{type(exc).__name__}: {exc}"
        logger.warning("specialist governance unavailable gate=%s error=%s", gate, detail)
        raise SpecialistGovernanceError(
            f"specialist {gate} governance could not be evaluated; refusing to launch",
            gate=gate,
            detail=detail,
        ) from exc

    async def _acquire_role_capacity_slot(self, specialist_role_key: str) -> None:
        try:
            limiter = RoleConcurrencyLimiter.instance()
            acquired = await limiter.acquire(specialist_role_key, timeout=0)
            if not acquired:
                raise SpecialistOrchestratorError(
                    f"Role '{specialist_role_key}' is at max concurrency; "
                    "specialist request refused to avoid unbounded spawning"
                )
        except SpecialistOrchestratorError:
            raise
        except Exception as exc:
            await self._raise_governance_failure(gate="concurrency", exc=exc)

    def _release_role_capacity_slot(
        self,
        child_task_id: str | None = None,
        *,
        specialist_role_key: str | None = None,
    ) -> None:
        role_key = specialist_role_key
        if child_task_id is not None:
            role_key = _SPECIALIST_ROLE_SLOTS_BY_CHILD.pop(child_task_id, None)
        if not role_key:
            return
        try:
            RoleConcurrencyLimiter.instance().release(role_key)
        except Exception:
            logger.debug(
                "specialist role slot release failed: child_task_id=%s role=%s",
                child_task_id,
                role_key,
                exc_info=True,
            )

    async def _enforce_budget_gate(self, parent_task: CodexTask) -> None:
        if not parent_task.issue_id:
            return
        issue = await self.store.load_codex_issue(parent_task.issue_id)
        if issue is None:
            raise SpecialistOrchestratorError(
                f"Issue {parent_task.issue_id} not found for specialist budget check"
            )
        try:
            budget_status = await compute_issue_budget_status(self.store, issue)
        except Exception as exc:
            await self._raise_governance_failure(gate="budget", exc=exc)
        if budget_status.over_budget:
            raise SpecialistOrchestratorError(
                "issue budget is exhausted; cannot launch a specialist child"
            )

    async def request_specialist(
        self,
        *,
        parent_task: CodexTask,
        specialist_role_key: str,
        specialist_prompt: str,
        why: str = "",
    ) -> CodexTask:
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
        latest_parent = await self.store.load_codex_task(parent_task.id)
        if latest_parent is None:
            raise SpecialistOrchestratorError(f"Parent task {parent_task.id} not found")
        parent_task = latest_parent

        # Validate parent task can make specialist calls
        if not is_task_active_status(parent_task.status) and not is_task_success_status(
            parent_task.status
        ):
            raise SpecialistOrchestratorError(
                f"Parent task {parent_task.id} must be running or just completed to request specialist (current status: {parent_task.status})"
            )
        if parent_task.task_kind == "specialist_child":
            raise SpecialistOrchestratorError(
                "Specialist child tasks cannot request further specialist calls (mesh depth ≤ 2)"
            )
        if not specialist_prompt or not str(specialist_prompt).strip():
            raise SpecialistOrchestratorError("Specialist prompt is required")
        if await self._has_unresolved_specialist_request(parent_task.id):
            raise SpecialistOrchestratorError(
                f"Parent task {parent_task.id} already has an unresolved specialist request"
            )

        # Validate specialist role exists in catalog
        if not specialist_role_key or not (
            specialist_role_key.startswith("specialist:")
            or specialist_role_key.startswith("custom:")
            or specialist_role_key == "operations_engineer"
        ):
            raise SpecialistOrchestratorError(
                f"Invalid specialist role key: {specialist_role_key}"
            )

        await self._acquire_role_capacity_slot(specialist_role_key)
        await self._enforce_budget_gate(parent_task)
        child_id: str | None = None
        slot_bound_to_child = False
        try:
            # Create specialist child task
            child_id = str(uuid4())
            now = datetime.now()

            specialist_executor = parent_task.executor or "claude"

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
                git_branch=parent_task.git_branch,
                git_base_branch=parent_task.git_base_branch,
                created_at=now,
                updated_at=now,
            )
            await self.store.save_codex_task(child)
            _SPECIALIST_ROLE_SLOTS_BY_CHILD[child.id] = specialist_role_key
            slot_bound_to_child = True

            # Pause parent task
            parent_task.status = "waiting_for_specialist"
            parent_task.blocked_by_help_id = _specialist_blocker_id(child.id)
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
                if parent_task.issue_id:
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
                logger.debug(
                    "specialist call feed message save failed: parent_task_id=%s",
                    parent_task.id,
                    exc_info=True,
                )

            # Emit events for real-time UI updates
            await self.event_bus.append(
                {
                    "type": "specialist_requested",
                    "parent_task_id": parent_task.id,
                    "child_task_id": child_id,
                    "project_id": parent_task.project_id,
                    "specialist_role": specialist_role_key,
                    "reason": why,
                }
            )
            await self.event_bus.append(
                build_task_status_event(parent_task, parent_task.status)
            )

            # Start the specialist child task. If the runner cannot start, do not
            # leave the parent suspended in waiting_for_specialist forever.
            try:
                await self.task_runner.start_task_run(child)
            except Exception as exc:
                self._release_role_capacity_slot(child.id)
                failed_at = datetime.now()
                child.status = "failed"
                child.result = f"Specialist child failed to start: {exc}"
                child.updated_at = failed_at
                await self.store.save_codex_task(child)

                parent_task.status = "ready_to_resume"
                parent_task.blocked_by_help_id = None
                parent_task.result = f"Specialist request failed to start: {exc}"
                parent_task.updated_at = failed_at
                await self.store.save_codex_task(parent_task)

                await self.event_bus.append(
                    {
                        "type": "specialist_failed",
                        "parent_task_id": parent_task.id,
                        "child_task_id": child.id,
                        "project_id": parent_task.project_id,
                        "specialist_role": specialist_role_key,
                        "error": parent_task.result,
                    }
                )
                await self.event_bus.append(
                    build_task_status_event(
                        child,
                        child.status,
                        result=child.result,
                    )
                )
                await self.event_bus.append(
                    build_task_status_event(
                        parent_task,
                        parent_task.status,
                        result=parent_task.result,
                    )
                )
                raise SpecialistOrchestratorError(
                    f"Failed to start specialist child task {child.id}: {exc}"
                ) from exc

            await self.event_bus.append(
                {
                    "type": "specialist_child_started",
                    "parent_task_id": parent_task.id,
                    "child_task_id": child_id,
                    "project_id": parent_task.project_id,
                    "specialist_role": specialist_role_key,
                }
            )

            return child
        except Exception:
            if slot_bound_to_child and child_id is not None:
                self._release_role_capacity_slot(child_id)
            else:
                self._release_role_capacity_slot(specialist_role_key=specialist_role_key)
            raise

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
        if child.task_kind != "specialist_child":
            raise SpecialistOrchestratorError(
                f"Task {specialist_child_task_id} is not a specialist child"
            )
        if not child.parent_task_id:
            raise SpecialistOrchestratorError(
                f"Specialist child task {specialist_child_task_id} has no parent task"
            )
        if is_task_terminal_status(child.status):
            self._release_role_capacity_slot(child.id)
        if not is_task_success_status(child.status):
            await self.event_bus.append(
                build_task_status_event(
                    child,
                    child.status,
                    result=child.result,
                )
            )
            if is_task_failure_status(child.status):
                parent = await self.store.load_codex_task(child.parent_task_id)
                if parent is not None and is_task_waiting_for_specialist_status(
                    parent.status
                ):
                    if parent.blocked_by_help_id != _specialist_blocker_id(child.id):
                        raise SpecialistOrchestratorError(
                            f"Parent task {parent.id} is waiting for a different specialist child"
                        )
                    parent.status = "ready_to_resume"
                    parent.blocked_by_help_id = None
                    parent.updated_at = datetime.now()
                    await self.store.save_codex_task(parent)
                    await self.event_bus.append(
                        {
                            "type": "specialist_failed",
                            "parent_task_id": parent.id,
                            "child_task_id": child.id,
                            "project_id": parent.project_id,
                            "specialist_role": child.role,
                            "error": child.result or f"Specialist child ended with {child.status}",
                        }
                    )
                    await self.event_bus.append(
                        build_task_status_event(
                            parent,
                            parent.status,
                            result=parent.result,
                        )
                    )
            raise SpecialistOrchestratorError(
                f"Specialist child task {specialist_child_task_id} is not done (current status: {child.status})"
            )

        parent = await self.store.load_codex_task(child.parent_task_id)
        if parent is None:
            raise SpecialistOrchestratorError(f"Parent task {child.parent_task_id} not found")
        if not is_task_waiting_for_specialist_status(parent.status):
            await self.event_bus.append(
                build_task_status_event(
                    parent,
                    parent.status,
                    result=parent.result,
                )
            )
            raise SpecialistOrchestratorError(
                f"Parent task {parent.id} is not waiting for specialist (current status: {parent.status})"
            )
        if parent.blocked_by_help_id != _specialist_blocker_id(child.id):
            await self.event_bus.append(
                build_task_status_event(
                    parent,
                    parent.status,
                    result=parent.result,
                )
            )
            raise SpecialistOrchestratorError(
                f"Parent task {parent.id} is waiting for a different specialist child"
            )

        now = datetime.now()

        # Inject specialist result into parent's review_comment for the continuation prompt
        persisted_result_summary = child.result if child.result is not None else specialist_result_summary
        specialist_continuation = (
            f"[SPECIALIST RESULT from {child.role}]\n\n{persisted_result_summary}\n\n"
            f"Review the above specialist findings and incorporate them into your next output."
        )
        if parent.review_comment:
            parent.review_comment = parent.review_comment + "\n\n" + specialist_continuation
        else:
            parent.review_comment = specialist_continuation

        # Reset parent to pending so it can resume with specialist findings
        parent.status = "pending"
        parent.blocked_by_help_id = None
        parent.updated_at = now
        await self.store.save_codex_task(parent)

        # Record specialist result as AgentMessage for the feed
        try:
            if parent.issue_id:
                graph = await self.store.load_workflow_graph_for_issue(parent.issue_id)
                msg = AgentMessage(
                    id=str(uuid4()),
                    issue_id=parent.issue_id,
                    graph_id=graph.id if graph else "",
                    from_node_key=child.role,  # specialist
                    to_node_key=parent.role,  # engineer or qa
                    message_type="specialist_result",
                    body=persisted_result_summary[:500],  # Truncate for feed display
                    created_at=now,
                )
                await self.store.save_agent_message(msg)
        except Exception:  # noqa: BLE001, RUF100
            logger.debug(
                "specialist result feed message save failed: child_task_id=%s",
                child.id,
                exc_info=True,
            )

        # Emit events
        await self.event_bus.append(
            {
                "type": "specialist_completed",
                "parent_task_id": parent.id,
                "child_task_id": specialist_child_task_id,
                "project_id": parent.project_id,
                "specialist_role": child.role,
            }
        )
        await self.event_bus.append(
            build_task_status_event(parent, parent.status)
        )

        return parent

    async def _has_unresolved_specialist_request(self, parent_task_id: str) -> bool:
        """Check if parent already has a specialist request in flight.

        The current wait is locked on the parent as ``specialist:<child_id>``.
        Historical terminal specialist children are not unresolved: after the
        parent resumes and runs again, it may legitimately request another
        specialist. Duplicate persist-result retries are still blocked because
        request_specialist reloads the parent and rejects non-runnable waiting
        or pending states before this helper can create another child.
        """
        parent = await self.store.load_codex_task(parent_task_id)
        if (
            parent is not None
            and is_task_waiting_for_specialist_status(parent.status)
            and str(parent.blocked_by_help_id or "").startswith("specialist:")
        ):
            return True
        list_tasks_raw = getattr(self.store, "list_codex_tasks", None)
        if not callable(list_tasks_raw):
            return False
        list_tasks = cast(ListCodexTasksFn, list_tasks_raw)
        children = await list_tasks(parent_task_id=parent_task_id)
        return any(
            c.task_kind == "specialist_child"
            and (is_task_pending_status(c.status) or is_task_active_status(c.status))
            for c in children
        )
