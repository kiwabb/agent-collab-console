from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime  # noqa: I001, RUF100
from typing import Protocol, cast
from uuid import uuid4

from app.application.help_orchestrator import is_help_request_terminal_status
from app.application.role_workflow_service import RoleWorkflowService
from app.application.runtime_catalog_service import RuntimeCatalogStore
from app.application.task_status_events import build_task_status_event
from app.application.task_statuses import (
    execution_process_state_for_task,
    is_task_active_status,
    is_task_failure_status,
    is_task_success_status,
    is_task_terminal_status,
)
from app.domain.models import (
    CodexIssue,
    CodexSession,
    CodexTask,
    ExecutionProcess,
    ExecutionProcessKind,
    HelpRequest,
)

logger = logging.getLogger(__name__)


JsonEvent = dict[str, object]
RefreshTaskResult = Callable[[CodexTask], Awaitable[object]]
ExecutionStartedCallback = Callable[[CodexTask, ExecutionProcess], Awaitable[None]]


class TaskRunnerStore(RuntimeCatalogStore, Protocol):
    async def save_execution_process(self, process: ExecutionProcess) -> None: ...

    async def save_codex_task(self, task: CodexTask) -> None: ...

    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...

    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> object: ...

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None: ...

    async def load_help_request(self, help_request_id: str) -> HelpRequest | None: ...

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None: ...

    async def save_codex_issue(self, issue: CodexIssue) -> None: ...


class TaskRunnerEventBus(Protocol):
    async def append(self, event: JsonEvent) -> None: ...


class TaskProcessManager(Protocol):
    async def write_input_async(
        self,
        session_id: str | None = None,
        input_text: str = "",
        **kwargs: object,
    ) -> str: ...


class HelpOrchestratorLike(Protocol):
    async def complete_help_request(
        self,
        help_request_id: str,
        *,
        child_status: str,
        child_result: str | None,
    ) -> object: ...


class RuntimeHelpSlot(Protocol):
    help_orchestrator: HelpOrchestratorLike | None


class CodexTaskRunner:
    _CODEX_COLLABORATION_HINT = (
        "This workspace includes project instructions in AGENTS.md and a local skill at "
        ".codex/skills/agent-collaboration-help. When you need focused help from Claude, "
        "follow those instructions and output exactly one raw JSON help request."
    )

    def __init__(
        self,
        codex_store: TaskRunnerStore,
        event_bus: TaskRunnerEventBus,
        process_manager_factory: Callable[[], TaskProcessManager],
        mock_manager_cls: type[object],
        refresh_task_result: RefreshTaskResult,
        help_orchestrator_factory: Callable[[], HelpOrchestratorLike] | None = None,
        role_workflow_service: RoleWorkflowService | None = None,
    ) -> None:
        self.codex_store = codex_store
        self.event_bus = event_bus
        self._process_manager_factory = process_manager_factory
        self._mock_manager_cls = mock_manager_cls
        self._refresh_task_result = refresh_task_result
        self._help_orchestrator_factory = help_orchestrator_factory
        self._role_workflow_service = role_workflow_service or RoleWorkflowService()

    async def _create_execution_process(
        self,
        task: CodexTask,
        executor: str,
        provider: str | None,
        model: str | None,
        *,
        kind: ExecutionProcessKind = "initial",
        triggering_message_id: str | None = None,
    ) -> ExecutionProcess:
        now = datetime.now()
        process = ExecutionProcess(
            id=str(uuid4()),
            task_id=task.id,
            session_id=task.session_id,
            status="Running",
            exit_code=None,
            executor=executor,
            provider=provider,
            model=model,
            kind=kind,
            triggering_message_id=triggering_message_id,
            started_at=now,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        await self.codex_store.save_execution_process(process)
        previous_trace_id = task.trace_id
        task.last_execution_process_id = process.id
        task.trace_id = process.id
        task.span_id = task.span_id or task.id
        if not task.parent_span_id and previous_trace_id and previous_trace_id != process.id:
            task.parent_span_id = previous_trace_id
        task.updated_at = now
        await self.codex_store.save_codex_task(task)
        return process

    async def start_task_run(
        self,
        task: CodexTask,
        *,
        prompt_override: str | None = None,
        resume_session_id: str | None = None,
        resume_message_id: str | None = None,
        run_executor: str | None = None,
        run_provider: str | None = None,
        run_model: str | None = None,
        kind: ExecutionProcessKind = "initial",
        triggering_message_id: str | None = None,
        wait_for_completion: bool = False,
        execution_started_callback: ExecutionStartedCallback | None = None,
        command_args_override: list[str] | None = None,
    ) -> ExecutionProcess:
        if is_task_active_status(task.status):
            raise ValueError("Task already running or responding")

        # Issue tasks MUST run inside their git worktree. If the worktree path
        # was never set (setup race or failure), reject now rather than letting
        # the runtime fall back to workspace.cwd (= the main project directory),
        # which would cause the agent to modify the main project instead of the
        # isolated branch.
        if getattr(task, "issue_id", None) and not getattr(task, "workspace_path", None):
            raise ValueError(
                f"Issue task {task.id} (issue={task.issue_id}) has no worktree path. "
                "Cannot run safely — aborting to prevent modification of the main project."
            )

        # Non-chat runs must not carry over the previous summary/result, or the
        # refresh step may skip extracting the new run's output from logs.
        if kind != "chat":
            task.result = None

        # Resolve effective executor/provider/model from runtime catalog
        # Also get rendered command args and env vars from templates
        (
            executor,
            provider,
            model,
            rendered_env,
            rendered_command_args,
            executor_type,
        ) = await self._resolve_effective_config(
            task,
            run_executor=run_executor,
            run_provider=run_provider,
            run_model=run_model,
        )

        task.status = "running"
        task.updated_at = datetime.now()
        await self.codex_store.save_codex_task(task)
        # Prime the activity tracker so the watchdog doesn't fire before the
        # first LLM token arrives (cold-start sometimes takes ~30s).
        from app.application import task_activity

        task_activity.touch(task.id)
        exec_process = await self._create_execution_process(
            task,
            executor,
            provider,
            model,
            kind=kind,
            triggering_message_id=triggering_message_id,
        )
        await self.event_bus.append(
            build_task_status_event(task, "running", execution_process_id=exec_process.id)
        )
        if execution_started_callback is not None:
            try:
                await execution_started_callback(task, exec_process)
            except Exception:
                logger.exception(
                    "task execution-start callback failed: task_id=%s process_id=%s",
                    task.id,
                    exec_process.id,
                )
                task.status = "failed"
                task.result = "task execution-start persistence failed"
                task.updated_at = datetime.now()
                await self.codex_store.save_codex_task(task)
                await self.codex_store.update_execution_process_status(
                    exec_process.id,
                    "Failed",
                    exit_code=-1,
                    completed_at=datetime.now(),
                )
                await self.event_bus.append(
                    build_task_status_event(
                        task,
                        "failed",
                        result=task.result,
                        execution_process_id=exec_process.id,
                    )
                )
                raise

        mgr = self._process_manager_factory()
        if self._help_orchestrator_factory is not None:
            help_orchestrator = self._help_orchestrator_factory()
            for runtime_name in ("_codex_runtime", "_claude_runtime"):
                runtime = getattr(mgr, runtime_name, None)
                if runtime is not None:
                    cast(RuntimeHelpSlot, runtime).help_orchestrator = help_orchestrator
        should_wait_for_completion = wait_for_completion or isinstance(mgr, self._mock_manager_cls)
        prompt_text = prompt_override if prompt_override is not None else task.prompt
        prompt_text = await self._build_prompt_text(
            task,
            kind=kind,
            prompt_text=prompt_text,
            prompt_override=prompt_override,
            resume_session_id=resume_session_id,
            resume_message_id=resume_message_id,
        )

        effective_command_args = [*(rendered_command_args or []), *(command_args_override or [])]
        try:
            final_status = await mgr.write_input_async(
                task.session_id,
                prompt_text,
                wait=should_wait_for_completion,
                task_id=task.id,
                executor=executor_type,  # Use executor_type for runtime routing
                provider=provider,
                model=model,
                resume_session_id=resume_session_id,
                resume_message_id=resume_message_id,
                cwd=task.workspace_path,
                env_overrides=rendered_env,
                command_args=effective_command_args,
                force_new_session=kind in ("rerun", "initial"),
            )
        except Exception:
            task.status = "failed"
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)
            await self.codex_store.update_execution_process_status(
                exec_process.id, "Failed", exit_code=-1, completed_at=datetime.now()
            )
            await self.event_bus.append(
                build_task_status_event(task, "failed", execution_process_id=exec_process.id)
            )
            raise

        task = await self.codex_store.load_codex_task(task.id) or task
        effective_status = task.status if is_task_terminal_status(task.status) else final_status
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
            await self.event_bus.append(
                build_task_status_event(
                    task,
                    task.status,
                    result=task.result,
                    execution_process_id=exec_process.id,
                )
            )
            await self._complete_help_child_if_needed(task)
            return exec_process

        # Reload after _refresh_task_result: persist_result may have triggered
        # request_specialist which sets the task to waiting_for_specialist in DB.
        # Saving the stale local copy would overwrite that status transition.
        reloaded = await self.codex_store.load_codex_task(task.id)
        if reloaded is not None and (
            is_task_failure_status(reloaded.status)
            or reloaded.status in ("waiting_for_specialist", "waiting_for_help")
        ):
            task = reloaded
        else:
            await self.codex_store.save_codex_task(task)

        # After a successful run, snapshot the worktree HEAD onto the owning
        # issue so the FE can show "N commits ahead of base" / merge-readiness.
        if is_task_success_status(task.status) and task.issue_id and task.git_worktree_path:
            try:
                from app.application.git_service import git_service as _git

                head = await _git.head_commit(task.git_worktree_path)
                issue = await self.codex_store.load_codex_issue(task.issue_id)
                if issue is not None and issue.git_last_commit_sha != head:
                    issue.git_last_commit_sha = head
                    issue.updated_at = datetime.now()
                    await self.codex_store.save_codex_issue(issue)
            except Exception:
                # Don't fail the run on a bookkeeping update.
                logger.debug("task git head bookkeeping failed: task_id=%s", task.id, exc_info=True)

        exec_final_status, exec_exit_code = execution_process_state_for_task(task.status)
        await self.codex_store.update_execution_process_status(
            exec_process.id,
            exec_final_status,
            exit_code=exec_exit_code,
            completed_at=datetime.now() if is_task_terminal_status(task.status) else None,
        )
        exec_process.status = exec_final_status
        await self.event_bus.append(
            build_task_status_event(
                task,
                task.status,
                result=task.result,
                review_comment=task.review_comment,
                execution_process_id=exec_process.id,
            )
        )
        await self._complete_help_child_if_needed(task)

        return exec_process

    def _read_current_artifact(self, task: CodexTask) -> str | None:
        """Read the role's canonical artifact for refine prompt building."""
        from app.application.issue_artifact_documents import IssueArtifactDocuments

        workspace_path = task.workspace_path
        if not workspace_path:
            return None
        docs = IssueArtifactDocuments()
        issue_id = task.issue_id or task.id
        role = getattr(task, "role", None)
        if role == "product_manager":
            p = docs.pm_prd_json_path(workspace_path, issue_id)
        elif role == "architect":
            p = docs.architect_system_design_json_path(workspace_path, issue_id)
        elif role == "engineer":
            p = docs.engineer_implementation_md_path(workspace_path, issue_id, task_id=task.id)
        elif role == "qa":
            p = docs.qa_plan_json_path(workspace_path, issue_id)
        else:
            return None
        try:
            return p.read_text(encoding="utf-8") if p.exists() else None
        except OSError:
            return None

    async def _build_prompt_text(
        self,
        task: CodexTask,
        *,
        prompt_text: str,
        prompt_override: str | None,
        resume_session_id: str | None,
        resume_message_id: str | None,
        kind: ExecutionProcessKind = "initial",
    ) -> str:
        # Chat mode: minimal prompt; CLI session resume carries history.
        # We intentionally do NOT call into role workflow's build_prompt here
        # (that would re-emit the full schema instructions and the agent would
        # produce JSON again, overwriting the artifact).
        if kind == "chat":
            # Strong system-prompt override. Weaker instruction-following models
            # (e.g. minimax) otherwise inherit the role workflow's "emit JSON"
            # directive from the prior turn and reply with the full artifact.
            return (
                "[SYSTEM OVERRIDE — CONVERSATIONAL CHAT MODE]\n"
                "Forget any previous instructions about JSON schemas or artifact output formats.\n"
                "You are now in plain-text chat mode. Strict rules for this turn:\n"
                "  1. Reply ONLY in natural language, like a human assistant chatting.\n"
                "  2. Do NOT output JSON, code fences, schema-conforming structures, or markdown tables.\n"
                "  3. Do NOT regenerate, repeat, or modify the task's stored artifact.\n"
                "  4. Keep the reply concise (1–3 short paragraphs is plenty).\n"  # noqa: RUF001
                "  5. If the user is just greeting you, greet back briefly.\n"
                "\n"
                f"User message:\n{prompt_text}\n"
                "\n"
                "Your natural-language reply:"
            )
        # Refine mode: embed the current canonical artifact and instruct agent to
        # re-emit the full artifact incorporating user-requested changes.
        if kind == "refine":
            existing = self._read_current_artifact(task)
            if existing is None:
                raise ValueError(
                    f"Refine requires a canonical artifact for task {task.id} (role={getattr(task, 'role', None)})"
                )
            return (
                "You previously produced this artifact for the task:\n\n```\n"
                + existing
                + "\n```\n\nThe user requests these changes:\n"
                + prompt_text
                + "\n\nRe-emit the FULL artifact (in the same JSON or markdown format) incorporating the requested changes. "
                + "Do not omit unchanged fields. Match the original schema exactly."
            )
        # Check if this is a managed role (using role_workflow_service)
        if (
            self._role_workflow_service.is_managed_role(task.role)
            and prompt_override is None
            and not (resume_session_id or resume_message_id)
        ):
            workspace = (
                await self.codex_store.load_codex_workspace(task.session_id)
                if self.codex_store is not None
                else None
            )
            workspace_title = workspace.title if workspace is not None else None
            # Resolve the project repo path so role builders can inject
            # accumulated team_notes.md context.
            project_repo_path = None
            if self.codex_store is not None and getattr(task, "project_id", None):
                load_project = getattr(self.codex_store, "load_project", None)
                if callable(load_project):
                    try:
                        proj = await load_project(task.project_id)
                        if proj is not None:
                            project_repo_path = proj.repo_path
                    except Exception:
                        project_repo_path = None
            managed_prompt = await self._role_workflow_service.build_prompt(
                task,
                workspace_title=workspace_title,
                project_repo_path=project_repo_path,
            )
            if isinstance(managed_prompt, str):
                return managed_prompt
        if task.executor != "codex":
            return prompt_text
        if prompt_override is not None:
            return prompt_text
        if resume_session_id or resume_message_id:
            return prompt_text
        return f"{self._CODEX_COLLABORATION_HINT}\n\n{prompt_text}"

    async def _complete_help_child_if_needed(self, task: CodexTask) -> None:
        if (
            self._help_orchestrator_factory is None
            or task.task_kind != "help_child"
            or not task.blocked_by_help_id
        ):
            return
        if not is_task_terminal_status(task.status):
            return

        help_orchestrator = self._help_orchestrator_factory()
        help_request = await self.codex_store.load_help_request(task.blocked_by_help_id)
        if help_request is None or is_help_request_terminal_status(help_request.status):
            return

        await help_orchestrator.complete_help_request(
            task.blocked_by_help_id,
            child_status=task.status,
            child_result=task.result,
        )

    async def _resolve_effective_config(
        self,
        task: CodexTask,
        run_executor: str | None = None,
        run_provider: str | None = None,
        run_model: str | None = None,
    ) -> tuple[str, str | None, str | None, dict[str, str] | None, list[str] | None, str]:
        """Resolve effective executor/provider/model for a task.

        Uses the runtime catalog to fill in defaults when task doesn't specify
        provider/model explicitly.

        Run-time overrides (run_executor, run_provider, run_model) take precedence
        over task defaults.

        Returns (executor, provider, model, rendered_env_overrides, rendered_command_args, executor_type).
        """
        from app.application.runtime_catalog_service import RuntimeCatalogService

        service = RuntimeCatalogService(self.codex_store)
        catalog = await service.load_catalog()

        # Priority: run override > task default > executor default
        executor = run_executor if run_executor is not None else (task.executor or "codex")
        provider = run_provider if run_provider is not None else task.provider
        model = run_model if run_model is not None else task.model

        (
            resolved_executor,
            resolved_provider,
            resolved_model,
            executor_env_overrides,
            executor_type,
        ) = service.resolve_effective_config(
            catalog,
            executor,
            provider=provider,
            model=model,
        )

        # If resolved config differs from task defaults, update the task
        # This persists the override as the new task default
        if (
            task.executor != resolved_executor
            or task.provider != resolved_provider
            or task.model != resolved_model
        ):
            task.executor = resolved_executor
            task.provider = resolved_provider
            task.model = resolved_model

        # Start with executor-level env overrides
        rendered_env = dict(executor_env_overrides) if executor_env_overrides else None

        # Render env templates and command template from provider config
        rendered_command_args = None
        if resolved_provider:
            provider_config = service._find_provider(catalog, resolved_executor, resolved_provider)
            if provider_config:
                context = {
                    "model": resolved_model or "",
                    "provider": resolved_provider or "",
                    "workspace_cwd": task.workspace_path or "",
                    "task_id": task.id,
                }
                # Render env_template (dict of env var names to template strings)
                if provider_config.env_template:
                    try:
                        if rendered_env is None:
                            rendered_env = {}
                        for env_key, env_template in provider_config.env_template.items():
                            rendered_env[env_key] = service.render_template(env_template, context)
                    except Exception:
                        logger.debug(
                            "runtime env template rendering failed: task_id=%s",
                            task.id,
                            exc_info=True,
                        )

                # Render command_template (string template for additional command args)
                if provider_config.command_template:
                    try:
                        rendered_cmd = service.render_template(
                            provider_config.command_template, context
                        )
                        # Split by whitespace to get individual args
                        rendered_command_args = rendered_cmd.split()
                    except Exception:
                        rendered_command_args = None

        return (
            resolved_executor,
            resolved_provider,
            resolved_model,
            rendered_env,
            rendered_command_args,
            executor_type,
        )
