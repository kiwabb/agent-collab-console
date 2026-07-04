from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.application.task_status_events import build_task_status_event
from app.application.task_statuses import (
    is_task_active_status,
    is_task_success_status,
    is_task_terminal_status,
    is_task_waiting_for_help_status,
    normalize_task_status,
)
from app.domain.models import CodexTask, CodexTaskMessage, HelpRequest

HELP_REQUEST_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "timed_out", "consumed", "resume_failed"}
)
HELP_REQUEST_RUNNING_STATUS = "running"


def is_help_request_running_status(status: object | None) -> bool:
    return normalize_task_status(status) == HELP_REQUEST_RUNNING_STATUS


def is_help_request_terminal_status(status: object | None) -> bool:
    return normalize_task_status(status) in HELP_REQUEST_TERMINAL_STATUSES


class HelpOrchestrator:
    def __init__(self, codex_store, event_bus, task_runner):
        self.codex_store = codex_store
        self.event_bus = event_bus
        self.task_runner = task_runner

    async def request_help(
        self, *, parent_task_id, target_executor, title, prompt, context_summary=None
    ):
        parent = await self._load_running_parent(parent_task_id)
        if not target_executor:
            raise ValueError("Help target executor is required")
        if not title or not str(title).strip():
            raise ValueError("Help title is required")
        if not prompt or not str(prompt).strip():
            raise ValueError("Help prompt is required")
        if target_executor == parent.executor:
            raise ValueError("Help target must differ from parent executor")
        if parent.task_kind == "help_child":
            raise ValueError("Help child tasks cannot request nested help")
        if await self._reconcile_unresolved_help(parent):
            raise ValueError("Parent task already has an unresolved help request")
        parent = await self._load_running_parent(parent_task_id)

        child_id = str(uuid4())
        help_request_id = str(uuid4())
        now = datetime.now()

        child = CodexTask(
            id=child_id,
            session_id=parent.session_id,
            project_id=parent.project_id,
            issue_id=parent.issue_id,
            phase=parent.phase,
            title=title,
            prompt=prompt,
            role=f"help:{target_executor}",
            executor=target_executor,
            status="pending",
            result=None,
            parent_task_id=parent.id,
            task_kind="help_child",
            blocked_by_help_id=help_request_id,
            workspace_path=parent.workspace_path,
            resume_session_id=None,
            resume_message_id=None,
            created_at=now,
            updated_at=now,
        )
        await self.codex_store.save_codex_task(child)

        help_request = HelpRequest(
            id=help_request_id,
            workspace_id=parent.session_id,
            parent_task_id=parent.id,
            child_task_id=child.id,
            source_executor=parent.executor,
            target_executor=target_executor,
            title=title,
            prompt=prompt,
            context_summary=context_summary,
            status="running",
            created_at=now,
            started_at=now,
        )
        await self.codex_store.save_help_request(help_request)

        parent.status = "waiting_for_help"
        parent.blocked_by_help_id = help_request.id
        parent.updated_at = now
        await self.codex_store.save_codex_task(parent)
        if parent.last_execution_process_id:
            await self.codex_store.update_execution_process_status(
                parent.last_execution_process_id,
                "Completed",
                completed_at=now,
            )

        await self.event_bus.append(
            {
                "type": "help_requested",
                "task_id": parent.id,
                "help_request_id": help_request.id,
                "child_task_id": child.id,
                "target": target_executor,
            }
        )
        await self.event_bus.append(
            build_task_status_event(
                parent,
                parent.status,
                execution_process_id=parent.last_execution_process_id,
            )
        )

        try:
            exec_process = await self.task_runner.start_task_run(child)
            child.status = "running"
            child.last_execution_process_id = getattr(exec_process, "id", None)
            child.updated_at = datetime.now()
            await self.codex_store.save_codex_task(child)
            await self.event_bus.append(
                build_task_status_event(
                    child,
                    child.status,
                    execution_process_id=child.last_execution_process_id,
                )
            )
        except Exception as exc:
            failure_time = datetime.now()
            failure_message = f"Failed to start help child task: {exc}"
            child.status = "failed"
            child.result = failure_message
            child.updated_at = failure_time
            await self.codex_store.save_codex_task(child)

            parent.status = "ready_to_resume"
            parent.blocked_by_help_id = None
            parent.updated_at = failure_time
            await self.codex_store.save_codex_task(parent)

            help_request.status = "failed"
            help_request.continuation_payload = {
                "type": "help_result",
                "help_request_id": help_request.id,
                "target": help_request.target_executor,
                "status": "failed",
                "error": {
                    "code": "help_child_start_failed",
                    "message": failure_message,
                },
            }
            help_request.completed_at = failure_time
            await self.codex_store.save_help_request(help_request)

            await self.event_bus.append(
                {
                    "type": "help_failed",
                    "task_id": parent.id,
                    "help_request_id": help_request.id,
                    "child_task_id": child.id,
                    "result": help_request.continuation_payload,
                }
            )
            await self.event_bus.append(
                build_task_status_event(
                    child,
                    child.status,
                    result=child.result,
                    execution_process_id=child.last_execution_process_id,
                )
            )
            await self.event_bus.append(
                build_task_status_event(
                    parent,
                    parent.status,
                    result=parent.result,
                    execution_process_id=parent.last_execution_process_id,
                )
            )
            raise RuntimeError(failure_message) from exc
        await self.event_bus.append(
            {
                "type": "help_child_started",
                "task_id": parent.id,
                "help_request_id": help_request.id,
                "child_task_id": child.id,
                "target": target_executor,
            }
        )
        return help_request

    async def request_help_from_runtime(
        self,
        *,
        task_id,
        workspace_id=None,
        source_executor=None,
        target_executor=None,
        title=None,
        prompt=None,
        context_summary=None,
    ):
        if source_executor is not None or workspace_id is not None:
            parent = await self.codex_store.load_codex_task(task_id)
            if parent is None:
                raise KeyError(task_id)
            if source_executor is not None and source_executor != parent.executor:
                raise ValueError("Help source executor must match parent executor")
            if workspace_id is not None and workspace_id != parent.session_id:
                raise ValueError("Help workspace must match parent workspace")
        return await self.request_help(
            parent_task_id=task_id,
            target_executor=target_executor,
            title=title,
            prompt=prompt,
            context_summary=context_summary,
        )

    async def complete_help_request(
        self, help_request_id: str, *, child_status: str, child_result: str | None
    ):
        help_request = await self.codex_store.load_help_request(help_request_id)
        if help_request is None:
            raise KeyError(help_request_id)
        if not is_help_request_running_status(help_request.status):
            raise ValueError("Help request is already terminal")

        parent = await self.codex_store.load_codex_task(help_request.parent_task_id)
        if parent is None:
            raise KeyError(help_request.parent_task_id)
        if (
            not is_task_waiting_for_help_status(parent.status)
            or parent.blocked_by_help_id != help_request.id
        ):
            raise ValueError("Parent task is not waiting for this help request")
        child = await self.codex_store.load_codex_task(help_request.child_task_id)
        if child is None:
            raise KeyError(help_request.child_task_id)
        if child.task_kind != "help_child":
            raise ValueError("Help request child task has invalid kind")
        if child.parent_task_id != parent.id:
            raise ValueError("Help request child task does not belong to parent")
        actual_child_status = str(child.status or "")
        if actual_child_status != child_status:
            child_status = actual_child_status
            child_result = child.result
        elif child.result is not None:
            child_result = child.result
        if not is_task_terminal_status(child_status):
            raise ValueError("Help child task is not terminal")

        completed_at = datetime.now()
        parent.status = "ready_to_resume"
        parent.blocked_by_help_id = None
        parent.updated_at = completed_at
        await self.codex_store.save_codex_task(parent)

        help_request.status = "completed" if is_task_success_status(child_status) else "failed"
        help_request.continuation_payload = self._build_continuation_payload(
            help_request, child_status, child_result
        )
        help_request.completed_at = completed_at
        await self.codex_store.save_help_request(help_request)

        if parent.last_execution_process_id:
            await self.codex_store.update_execution_process_status(
                parent.last_execution_process_id,
                "Completed",
                completed_at=parent.updated_at,
            )
        event_type = "help_completed" if is_task_success_status(child_status) else "help_failed"
        await self.event_bus.append(
            {
                "type": event_type,
                "task_id": parent.id,
                "help_request_id": help_request.id,
                "child_task_id": help_request.child_task_id,
                "result": help_request.continuation_payload,
            }
        )

        try:
            if await self._try_auto_resume_parent(parent, help_request):
                return await self.codex_store.load_help_request(help_request.id) or help_request
        except Exception as exc:
            help_request.status = "resume_failed"
            help_request.continuation_payload = {
                **(help_request.continuation_payload or {}),
                "resume_error": {
                    "code": "parent_auto_resume_failed",
                    "message": str(exc),
                },
            }
            await self.codex_store.save_help_request(help_request)

        await self._mark_parent_ready_to_resume(parent, help_request, child_status, child_result)
        return help_request

    async def _try_auto_resume_parent(self, parent: CodexTask, help_request: HelpRequest) -> bool:
        resume_session_id = parent.resume_session_id
        resume_message_id = parent.resume_message_id

        # Per-task session identity: a parent must resume only its OWN captured
        # session. Never borrow the shared per-workspace thread pointer — that
        # would resume an unrelated role's session. If the parent has no session
        # of its own, fall through to the manual ready_to_resume path.
        if not resume_session_id:
            return False

        continuation_prompt = self._build_continuation_prompt(
            help_request.continuation_payload or {}
        )
        parent.status = "pending"
        parent.updated_at = datetime.now()
        await self.codex_store.save_codex_task(parent)
        await self.task_runner.start_task_run(
            parent,
            prompt_override=continuation_prompt,
            resume_session_id=resume_session_id,
            resume_message_id=resume_message_id,
        )

        help_request.status = "consumed"
        help_request.consumed_at = datetime.now()
        await self.codex_store.save_help_request(help_request)
        return True

    async def _load_running_parent(self, task_id: str):
        task = await self.codex_store.load_codex_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if not is_task_active_status(task.status):
            raise ValueError("Parent task must be running to request help")
        return task

    async def _has_unresolved_help(self, parent_task_id: str) -> bool:
        requests = await self.codex_store.list_help_requests(parent_task_id=parent_task_id)
        return any(
            not is_help_request_terminal_status(request.status)
            for request in requests
        )

    async def _reconcile_unresolved_help(self, parent: CodexTask) -> bool:
        """Repair crash-window help state before deciding whether to allow a
        new help request.

        ``request_help`` writes child + help_request before it can lock the
        parent. If the process crashes in that window, a later help request sees
        an unresolved help_request while the parent still appears runnable. Best
        effort reconciliation restores the parent lock, and if the child is
        already terminal it completes the request before returning.
        """
        requests = await self.codex_store.list_help_requests(parent_task_id=parent.id)
        for help_request in requests:
            if is_help_request_terminal_status(help_request.status):
                continue
            child = await self.codex_store.load_codex_task(help_request.child_task_id)
            if (
                not is_task_waiting_for_help_status(parent.status)
                or parent.blocked_by_help_id != help_request.id
            ):
                parent.status = "waiting_for_help"
                parent.blocked_by_help_id = help_request.id
                parent.updated_at = datetime.now()
                await self.codex_store.save_codex_task(parent)
                await self.event_bus.append(
                    build_task_status_event(
                        parent,
                        parent.status,
                        execution_process_id=parent.last_execution_process_id,
                    )
                )
            if child is not None and is_task_terminal_status(child.status):
                await self.complete_help_request(
                    help_request.id,
                    child_status=child.status,
                    child_result=child.result,
                )
                continue
            return True
        return False

    async def _mark_parent_ready_to_resume(
        self,
        parent: CodexTask,
        help_request: HelpRequest,
        child_status: str,
        child_result: str | None,
    ) -> None:
        parent.status = "ready_to_resume"
        parent.blocked_by_help_id = None
        parent.updated_at = datetime.now()
        await self.codex_store.save_codex_task(parent)
        await self.codex_store.save_codex_task_message(
            CodexTaskMessage(
                id=str(uuid4()),
                task_id=parent.id,
                execution_process_id=None,
                role="assistant",
                content=self._build_help_result_message(help_request, child_status, child_result),
                created_at=datetime.now(),
            )
        )
        await self.event_bus.append(
            build_task_status_event(
                parent,
                parent.status,
                result=parent.result,
                execution_process_id=parent.last_execution_process_id,
            )
        )

    def _build_continuation_payload(
        self, help_request: HelpRequest, child_status: str, child_result: str | None
    ):
        status = "completed" if is_task_success_status(child_status) else "failed"
        payload = {
            "type": "help_result",
            "help_request_id": help_request.id,
            "target": help_request.target_executor,
            "status": status,
        }
        if is_task_success_status(child_status):
            payload["result"] = {
                "summary": child_result or "",
                "raw_result": child_result or "",
            }
        else:
            payload["error"] = {
                "code": "child_task_failed",
                "message": child_result or "Help task failed",
            }
        return payload

    def _build_continuation_prompt(self, payload: dict):
        if payload.get("status") == "completed":
            result = payload.get("result") or {}
            return (
                "System continuation:\n"
                "Your help request has completed.\n\n"
                f"Help request id: {payload['help_request_id']}\n"
                f"Status: {payload['status']}\n\n"
                "Help result:\n"
                f"{result.get('raw_result', '')}"
            )
        error = payload.get("error") or {}
        return (
            "System continuation:\n"
            "Your help request failed.\n\n"
            f"Help request id: {payload['help_request_id']}\n"
            f"Status: {payload['status']}\n\n"
            "Error:\n"
            f"{error.get('message', '')}"
        )

    def _build_help_result_message(
        self, help_request: HelpRequest, child_status: str, child_result: str | None
    ) -> str:
        helper_name = "Claude" if help_request.target_executor == "claude" else "Codex"
        if is_task_success_status(child_status):
            return f"{helper_name} help result:\n{child_result or ''}".rstrip()
        return f"{helper_name} help failed:\n{child_result or 'Help task failed'}".rstrip()
