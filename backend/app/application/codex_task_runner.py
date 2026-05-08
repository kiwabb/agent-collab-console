from datetime import datetime
from uuid import uuid4

from app.domain.models import ExecutionProcess
from app.application.role_workflow_service import RoleWorkflowService


class CodexTaskRunner:
    _CODEX_COLLABORATION_HINT = (
        "This workspace includes project instructions in AGENTS.md and a local skill at "
        ".codex/skills/agent-collaboration-help. When you need focused help from Claude, "
        "follow those instructions and output exactly one raw JSON help request."
    )

    def __init__(self, codex_store, event_bus, process_manager_factory, mock_manager_cls, refresh_task_result, help_orchestrator_factory=None, role_workflow_service=None):
        self.codex_store = codex_store
        self.event_bus = event_bus
        self._process_manager_factory = process_manager_factory
        self._mock_manager_cls = mock_manager_cls
        self._refresh_task_result = refresh_task_result
        self._help_orchestrator_factory = help_orchestrator_factory
        self._role_workflow_service = role_workflow_service or RoleWorkflowService()

    async def _create_execution_process(self, task):
        now = datetime.now()
        process = ExecutionProcess(
            id=str(uuid4()),
            task_id=task.id,
            session_id=task.session_id,
            status="Running",
            exit_code=None,
            started_at=now,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        await self.codex_store.save_execution_process(process)
        task.last_execution_process_id = process.id
        task.updated_at = now
        await self.codex_store.save_codex_task(task)
        return process

    async def start_task_run(
        self,
        task,
        *,
        prompt_override=None,
        resume_session_id=None,
        resume_message_id=None,
    ):
        if task.status == "running":
            raise ValueError("Task already running")

        task.status = "running"
        task.updated_at = datetime.now()
        await self.codex_store.save_codex_task(task)
        exec_process = await self._create_execution_process(task)
        await self.event_bus.append({
            "type": "task_status",
            "task_id": task.id,
            "workspace_id": task.session_id,
            "session_id": task.session_id,
            "status": "running",
            "execution_process_id": exec_process.id,
        })

        mgr = self._process_manager_factory()
        if self._help_orchestrator_factory is not None:
            help_orchestrator = self._help_orchestrator_factory()
            for runtime_name in ("_codex_runtime", "_claude_runtime"):
                runtime = getattr(mgr, runtime_name, None)
                if runtime is not None:
                    runtime.help_orchestrator = help_orchestrator
        wait_for_completion = isinstance(mgr, self._mock_manager_cls)
        prompt_text = prompt_override if prompt_override is not None else task.prompt
        prompt_text = await self._build_prompt_text(
            task,
            prompt_text=prompt_text,
            prompt_override=prompt_override,
            resume_session_id=resume_session_id,
            resume_message_id=resume_message_id,
        )

        try:
            final_status = await mgr.write_input_async(
                task.session_id,
                prompt_text + "\n",
                wait=wait_for_completion,
                task_id=task.id,
                executor=task.executor,
                resume_session_id=resume_session_id,
                resume_message_id=resume_message_id,
                cwd=task.workspace_path,
            )
        except Exception:
            task.status = "failed"
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)
            await self.codex_store.update_execution_process_status(exec_process.id, "Failed", exit_code=-1, completed_at=datetime.now())
            await self.event_bus.append({
                "type": "task_status",
                "task_id": task.id,
                "workspace_id": task.session_id,
                "session_id": task.session_id,
                "status": "failed",
                "execution_process_id": exec_process.id,
            })
            raise

        task = await self.codex_store.load_codex_task(task.id) or task
        if task.status in {"done", "failed", "cancelled"}:
            effective_status = task.status
        else:
            effective_status = final_status
        task.status = effective_status
        task.updated_at = datetime.now()
        try:
            await self._refresh_task_result(task)
        except Exception as exc:
            task.status = "failed"
            task.result = str(exc)
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)
            await self.codex_store.update_execution_process_status(
                exec_process.id,
                "Failed",
                exit_code=-1,
                completed_at=datetime.now(),
            )
            exec_process.status = "Failed"
            await self.event_bus.append({
                "type": "task_status",
                "task_id": task.id,
                "workspace_id": task.session_id,
                "session_id": task.session_id,
                "status": task.status,
                "result": task.result,
                "execution_process_id": exec_process.id,
            })
            await self._complete_help_child_if_needed(task)
            return exec_process
        await self.codex_store.save_codex_task(task)

        exec_final_status = "Completed" if task.status == "done" else "Running"
        await self.codex_store.update_execution_process_status(
            exec_process.id,
            exec_final_status,
            exit_code=0 if task.status == "done" else None,
            completed_at=datetime.now() if task.status == "done" else None,
        )
        exec_process.status = exec_final_status
        await self.event_bus.append({
            "type": "task_status",
            "task_id": task.id,
            "workspace_id": task.session_id,
            "session_id": task.session_id,
            "status": task.status,
            "result": task.result,
            "execution_process_id": exec_process.id,
        })
        await self._complete_help_child_if_needed(task)

        return exec_process

    async def _build_prompt_text(self, task, *, prompt_text: str, prompt_override: str | None, resume_session_id: str | None, resume_message_id: str | None) -> str:
        # Check if this is a managed role (using role_workflow_service)
        if self._role_workflow_service.is_managed_role(task.role) and prompt_override is None and not (resume_session_id or resume_message_id):
            workspace = await self.codex_store.load_codex_workspace(task.session_id) if self.codex_store is not None else None
            workspace_title = workspace.title if workspace is not None else None
            managed_prompt = self._role_workflow_service.build_prompt(task, workspace_title=workspace_title)
            if managed_prompt is not None:
                return managed_prompt
        if task.executor != "codex":
            return prompt_text
        if prompt_override is not None:
            return prompt_text
        if resume_session_id or resume_message_id:
            return prompt_text
        return f"{self._CODEX_COLLABORATION_HINT}\n\n{prompt_text}"

    async def _complete_help_child_if_needed(self, task):
        if self._help_orchestrator_factory is None or task.task_kind != "help_child" or not task.blocked_by_help_id:
            return
        if task.status not in {"done", "failed"}:
            return

        help_orchestrator = self._help_orchestrator_factory()
        help_request = await self.codex_store.load_help_request(task.blocked_by_help_id)
        if help_request is None or help_request.status in {"completed", "failed", "timed_out", "consumed"}:
            return

        await help_orchestrator.complete_help_request(
            task.blocked_by_help_id,
            child_status=task.status,
            child_result=task.result,
        )
