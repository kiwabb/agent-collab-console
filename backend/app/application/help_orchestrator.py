from datetime import datetime
from uuid import uuid4

from app.domain.models import CodexTask, CodexTaskMessage, HelpRequest


class HelpOrchestrator:
    def __init__(self, codex_store, event_bus, task_runner):
        self.codex_store = codex_store
        self.event_bus = event_bus
        self.task_runner = task_runner

    async def request_help(self, *, parent_task_id, target_executor, title, prompt, context_summary=None):
        parent = await self._load_running_parent(parent_task_id)
        if target_executor == parent.executor:
            raise ValueError("Help target must differ from parent executor")
        if parent.task_kind == "help_child":
            raise ValueError("Help child tasks cannot request nested help")
        if await self._has_unresolved_help(parent.id):
            raise ValueError("Parent task already has an unresolved help request")

        child_id = str(uuid4())
        help_request_id = str(uuid4())
        now = datetime.now()

        child = CodexTask(
            id=child_id,
            session_id=parent.session_id,
            title=title,
            prompt=prompt,
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

        await self.event_bus.append({
            "type": "help_requested",
            "task_id": parent.id,
            "help_request_id": help_request.id,
            "child_task_id": child.id,
            "target": target_executor,
        })
        await self.event_bus.append({
            "type": "task_status",
            "task_id": parent.id,
            "session_id": parent.session_id,
            "status": parent.status,
            "execution_process_id": parent.last_execution_process_id,
        })

        await self.task_runner.start_task_run(child)
        await self.event_bus.append({
            "type": "help_child_started",
            "task_id": parent.id,
            "help_request_id": help_request.id,
            "child_task_id": child.id,
            "target": target_executor,
        })
        return help_request

    async def request_help_from_runtime(self, *, task_id, workspace_id=None, source_executor=None, target_executor=None, title=None, prompt=None, context_summary=None):
        return await self.request_help(
            parent_task_id=task_id,
            target_executor=target_executor,
            title=title,
            prompt=prompt,
            context_summary=context_summary,
        )

    async def complete_help_request(self, help_request_id: str, *, child_status: str, child_result: str | None):
        help_request = await self.codex_store.load_help_request(help_request_id)
        if help_request is None:
            raise KeyError(help_request_id)

        parent = await self.codex_store.load_codex_task(help_request.parent_task_id)
        if parent is None:
            raise KeyError(help_request.parent_task_id)

        completed_at = datetime.now()
        help_request.status = "completed" if child_status == "done" else "failed"
        help_request.continuation_payload = self._build_continuation_payload(help_request, child_status, child_result)
        help_request.completed_at = completed_at
        await self.codex_store.save_help_request(help_request)

        parent.blocked_by_help_id = None
        parent.updated_at = completed_at
        await self.codex_store.save_codex_task(parent)
        if parent.last_execution_process_id:
            await self.codex_store.update_execution_process_status(
                parent.last_execution_process_id,
                "Completed",
                completed_at=parent.updated_at,
            )
        event_type = "help_completed" if child_status == "done" else "help_failed"
        await self.event_bus.append({
            "type": event_type,
            "task_id": parent.id,
            "help_request_id": help_request.id,
            "child_task_id": help_request.child_task_id,
            "result": help_request.continuation_payload,
        })

        if await self._try_auto_resume_parent(parent, help_request):
            return await self.codex_store.load_help_request(help_request.id) or help_request

        parent.status = "ready_to_resume"
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
        await self.event_bus.append({
            "type": "task_status",
            "task_id": parent.id,
            "session_id": parent.session_id,
            "status": parent.status,
            "result": parent.result,
            "execution_process_id": parent.last_execution_process_id,
        })
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

        continuation_prompt = self._build_continuation_prompt(help_request.continuation_payload or {})
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
        if task.status not in {"running", "responding"}:
            raise ValueError("Parent task must be running to request help")
        return task

    async def _has_unresolved_help(self, parent_task_id: str) -> bool:
        requests = await self.codex_store.list_help_requests(parent_task_id=parent_task_id)
        return any(request.status not in {"completed", "failed", "timed_out", "consumed"} for request in requests)

    def _build_continuation_payload(self, help_request: HelpRequest, child_status: str, child_result: str | None):
        status = "completed" if child_status == "done" else "failed"
        payload = {
            "type": "help_result",
            "help_request_id": help_request.id,
            "target": help_request.target_executor,
            "status": status,
        }
        if child_status == "done":
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

    def _build_help_result_message(self, help_request: HelpRequest, child_status: str, child_result: str | None) -> str:
        helper_name = "Claude" if help_request.target_executor == "claude" else "Codex"
        if child_status == "done":
            return f"{helper_name} help result:\n{child_result or ''}".rstrip()
        return f"{helper_name} help failed:\n{child_result or 'Help task failed'}".rstrip()
