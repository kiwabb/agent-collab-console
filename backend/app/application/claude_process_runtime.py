from __future__ import annotations

import asyncio  # noqa: I001, RUF100
import json
import os
from datetime import datetime

from app.adapters.local_process import run_trusted_local
from app.application import timeouts
from app.application.process_runtime_common import (
    AsyncProcessEntry,
    BaseProcessRuntime,
    RefreshTaskResult,
    RuntimeCodexStore,
    RuntimeEventBus,
    RuntimeHelpOrchestrator,
    RuntimeLogStore,
    is_workspace_console_task,
)
from app.application.task_statuses import is_task_terminal_status


class ClaudeProcessRuntime(BaseProcessRuntime):
    def __init__(
        self,
        codex_store: RuntimeCodexStore,
        log_store: RuntimeLogStore,
        data_dir: str | None = None,
        event_bus: RuntimeEventBus | None = None,
        processes: dict[str, AsyncProcessEntry] | None = None,
        help_orchestrator: RuntimeHelpOrchestrator | None = None,
        refresh_task_result: RefreshTaskResult | None = None,
    ) -> None:
        super().__init__(
            codex_store,
            log_store,
            data_dir=data_dir,
            event_bus=event_bus,
            processes=processes,
            help_orchestrator=help_orchestrator,
            refresh_task_result=refresh_task_result,
        )
        self._claude_cmd = timeouts.claude_cmd().split()

    def check_availability(self) -> bool:
        try:
            return (
                run_trusted_local(
                    [self._claude_cmd[0], "--version"],
                    capture_output=True,
                ).returncode
                == 0
            )
        except Exception:
            return False

    async def write_input_async(
        self,
        *,
        workspace_id: str | None = None,
        input_text: str,
        wait: bool = True,
        task_id: str | None = None,
        executor: str = "claude",
        provider: str | None = None,
        model: str | None = None,
        resume_session_id: str | None = None,
        resume_message_id: str | None = None,
        cwd: str | None = None,
        env_overrides: dict[str, str] | None = None,
        command_args: list[str] | None = None,
        force_new_session: bool = False,
        **legacy_kwargs: object,
    ) -> str:
        """Write input using asyncio subprocess."""
        workspace_id = self._resolve_workspace_id(workspace_id, **legacy_kwargs)
        process_key = task_id or workspace_id
        entry = self._processes.get(process_key)
        evt = asyncio.Event() if wait else None

        if entry is None or not entry.alive:
            if entry is not None:
                self._processes.pop(process_key, None)
                await self._cleanup_entry(process_key, entry)
            entry = await self._spawn_process_async(
                workspace_id=workspace_id,
                resume_session_id=resume_session_id,
                resume_message_id=resume_message_id,
                task_id=task_id,
                waiter=evt,
                cwd=cwd,
                provider=provider,
                model=model,
                env_overrides=env_overrides,
                command_args=command_args,
                force_new_session=force_new_session,
            )
        else:
            if evt:
                entry.pending_waiters.append(evt)

        await self._append_log(workspace_id, "stdin", input_text, task_id)
        try:
            input_payload = self._encode_claude_input(input_text).encode("utf-8")
            stdin = entry.proc.stdin
            if stdin is None:
                raise BrokenPipeError("Claude subprocess stdin is closed")
            stdin.write(input_payload)
            await stdin.drain()
        except (BrokenPipeError, OSError, AttributeError):
            # Process died, retry once by respawning
            self._processes.pop(process_key, None)
            await self._cleanup_entry(process_key, entry)
            entry = await self._spawn_process_async(
                workspace_id=workspace_id,
                resume_session_id=resume_session_id,
                resume_message_id=resume_message_id,
                task_id=task_id,
                waiter=evt,
                cwd=cwd,
                provider=provider,
                model=model,
                env_overrides=env_overrides,
                command_args=command_args,
                force_new_session=force_new_session,
            )

        if wait and evt:
            timeout_s = timeouts.process_max_timeout_s()
            try:
                await asyncio.wait_for(evt.wait(), timeout=timeout_s)
            except asyncio.TimeoutError:  # noqa: UP041
                await self._abort_wait_timeout(
                    process_key,
                    entry,
                    task_id=task_id,
                    timeout_s=timeout_s,
                )
                return "timeout"
            return "done"

        return "responding"

    async def _abort_wait_timeout(
        self,
        process_key: str,
        entry: AsyncProcessEntry,
        *,
        task_id: str | None,
        timeout_s: float,
    ) -> None:
        """Terminate and persist failure before a synchronous wait returns."""
        self._processes.pop(process_key, None)
        entry.had_error = True
        entry.timeout_reason = "turn_timeout"
        entry.result_text = f"Claude runtime exceeded maximum wait of {timeout_s:g} seconds"
        await self._cleanup_entry(process_key, entry)
        if task_id is None:
            return
        task = await self.codex_store.load_codex_task(task_id)
        if task is not None and not is_task_terminal_status(task.status):
            await self._mark_task_failed(task_id, entry)

    def _owns_entry(self, entry: AsyncProcessEntry) -> bool:
        return getattr(entry, "executor", None) == "claude"

    async def _spawn_process_async(
        self,
        workspace_id: str,
        resume_session_id: str | None,
        resume_message_id: str | None,
        task_id: str | None,
        waiter: asyncio.Event | None,
        cwd: str | None,
        provider: str | None = None,
        model: str | None = None,
        env_overrides: dict[str, str] | None = None,
        command_args: list[str] | None = None,
        force_new_session: bool = False,
    ) -> AsyncProcessEntry:
        """Async version of _spawn_process using asyncio.create_subprocess_exec."""
        workspace = await self.codex_store.load_codex_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")

        workspace.status = "responding"
        workspace.last_active_at = datetime.now()
        await self.codex_store.save_codex_workspace(workspace)

        if self._event_bus is not None:
            await self._event_bus.append(
                {
                    "type": "session_status",
                    "session_id": workspace_id,
                    "workspace_id": workspace_id,
                    "status": "responding",
                }
            )

        # Per-task session identity: only the human workspace-console task may fall
        # back to the shared workspace.claude_thread_id. Role/help tasks resume only
        # their own task.resume_session_id (passed in), never the shared pointer —
        # so one broken session can't poison every role in the workspace.
        task = await self.codex_store.load_codex_task(task_id) if task_id else None
        # Issue tasks must run in their isolated worktree, never fall back to
        # workspace.cwd (= main project repo). Falling back would let the agent
        # modify the main project instead of the issue branch.
        task_issue_id = getattr(task, "issue_id", None) if task is not None else None
        if task_issue_id and not cwd:
            raise ValueError(
                f"Issue task {task_id} (issue={task_issue_id}) has no worktree cwd. "
                "Refusing to run in main project directory."
            )
        effective_cwd = cwd or getattr(workspace, "cwd", None) or self._data_dir
        allow_ws_fallback = task is None or is_workspace_console_task(task)
        ws_fallback_id = workspace.claude_thread_id if allow_ws_fallback else None
        # When force_new_session=True, do NOT fall back to the workspace pointer.
        effective_resume_id = (
            resume_session_id if force_new_session else (resume_session_id or ws_fallback_id)
        )
        runtime_catalog_controls_api = bool(
            env_overrides
            and ("ANTHROPIC_BASE_URL" in env_overrides or "ANTHROPIC_API_KEY" in env_overrides)
        )
        cmd = self._build_claude_command(
            effective_resume_id,
            resume_message_id=resume_message_id,
            model=model,
            setting_sources="project,local" if runtime_catalog_controls_api else None,
        )

        env = os.environ.copy()
        paths = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
            os.path.expanduser("~/.npm-global/bin"),
        ]
        env["PATH"] = ":".join(paths) + ":" + env.get("PATH", "")
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

        # Set provider/model env vars if specified
        if provider:
            env["CLAUDE_PROVIDER"] = provider
        if model:
            env["CLAUDE_MODEL"] = model

        # Apply rendered env overrides from runtime catalog templates
        if env_overrides:
            env.update(env_overrides)

        # Append rendered command args from runtime catalog templates
        if command_args:
            cmd.extend(command_args)

        proc = await asyncio.create_subprocess_exec(
            cmd[0],
            *cmd[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=effective_cwd,
            env=env,
            start_new_session=True,
            # Raise the StreamReader line limit (default 64KB) so a single large
            # stream-json line (a big tool result / long assistant turn) doesn't
            # raise LimitOverrunError and break the reader loop.
            limit=4 * 1024 * 1024,
        )

        # Audit the CLI spawn (PR2): the full launched command line + cwd +
        # model/provider + resume id. Best-effort fire-and-forget. The trailing
        # prompt arg is redacted (it can be large and carry sensitive context;
        # the prompt is already persisted as the task/role artifact elsewhere) —
        # the audit row captures HOW the process was launched, not the prompt.
        self._audit_cli_spawn(
            cmd=cmd,
            cwd=effective_cwd,
            task_id=task_id,
            execution_process_id=getattr(task, "last_execution_process_id", None),
            workspace_id=workspace_id,
            provider=provider,
            model=model,
            resume_session_id=effective_resume_id,
            pid=getattr(proc, "pid", None),
            trace_id=getattr(task, "trace_id", None),
            span_id=getattr(task, "span_id", None),
            parent_span_id=getattr(task, "parent_span_id", None),
        )

        entry = AsyncProcessEntry(
            proc=proc,
            output_task=None,
            alive=True,
            session_id=workspace_id,
            task_id=task_id,
            executor="claude",
            cwd=effective_cwd,
            resume_session_id=effective_resume_id,
            resume_message_id=resume_message_id,
            pending_waiters=[waiter] if waiter else [],
        )

        entry.output_task = asyncio.create_task(self._reader_loop(workspace_id, entry, task_id))
        self._processes[task_id or workspace_id] = entry
        return entry

    @staticmethod
    def _audit_cli_spawn(
        *,
        cmd: list[str],
        cwd: str | None,
        task_id: str | None,
        workspace_id: str | None,
        provider: str | None,
        model: str | None,
        resume_session_id: str | None,
        pid: int | None,
        execution_process_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> None:
        """Record a CLI subprocess launch into the unified audit_log.

        Thin forwarding shell over `audit.record_cli_spawn` — the shaping
        (trailing-prompt redaction, payload layout) lives in the audit package
        now. Kept as a static method so existing tests call it directly.
        """
        from app.application import audit

        audit.record_cli_spawn(
            cmd=cmd,
            cwd=cwd,
            task_id=task_id,
            execution_process_id=execution_process_id,
            workspace_id=workspace_id,
            provider=provider,
            model=model,
            resume_session_id=resume_session_id,
            pid=pid,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
        )

    def _build_claude_command(
        self,
        resume_session_id: str | None,
        prompt_text: str | None = None,
        resume_message_id: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        agent: str | None = None,
        approval_mode: bool = False,
        setting_sources: str | None = None,
    ) -> list[str]:
        base = list(self._claude_cmd)

        if "-p" not in base and "--print" not in base:
            base = [base[0], "-p", *base[1:]]
        if "--output-format=stream-json" not in base:
            base.append("--output-format=stream-json")
        if "--input-format=stream-json" not in base:
            base.append("--input-format=stream-json")
        if "--include-partial-messages" not in base:
            base.append("--include-partial-messages")
        if "--replay-user-messages" not in base:
            base.append("--replay-user-messages")

        joined = " ".join(base)
        if model and f"--model={model}" not in joined and "--model" not in joined:
            base.extend(["--model", model])
        if effort and f"--effort={effort}" not in joined and "--effort" not in joined:
            base.extend(["--effort", effort])
        if agent and f"--agent={agent}" not in joined and "--agent" not in joined:
            base.extend(["--agent", agent])
        if (
            setting_sources
            and "--setting-sources" not in base
            and not any(arg.startswith("--setting-sources=") for arg in base)
        ):
            # Runtime-catalog API credentials must not be overwritten by
            # ~/.claude/settings.json env entries (for example a personal
            # ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL for another gateway).
            # Keep project/local settings, but exclude user settings only when
            # the catalog explicitly owns the API endpoint/key.
            base.extend(["--setting-sources", setting_sources])

        # Clean up any existing permission flags to avoid duplicates/conflicts
        base = [arg for arg in base if not arg.startswith("--permission-mode=")]
        base = [arg for arg in base if not arg.startswith("--permission-prompt-tool=")]
        # Always enable correct permission bypass for automated background tasks
        base.append("--permission-prompt-tool=stdio")
        base.append("--permission-mode=bypassPermissions")

        if not approval_mode:  # noqa: SIM102
            if "--disallowedTools=AskUserQuestion" not in " ".join(base):
                base.append("--disallowedTools=AskUserQuestion")

        if resume_session_id and "--resume" not in base and "-r" not in base:
            base.extend(["--resume", resume_session_id])
        if resume_message_id and "--resume-session-at" not in base:
            base.extend(["--resume-session-at", resume_message_id])

        return [*base, prompt_text] if prompt_text else base

    def _encode_claude_input(self, input_text: str) -> str:
        payload = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": input_text.rstrip("\n"),
                    }
                ],
            },
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
