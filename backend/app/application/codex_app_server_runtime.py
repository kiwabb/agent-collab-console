import asyncio
import json
import os
import shlex
import subprocess
from datetime import datetime

from app.application.json_rpc_client import AppServerClient, AsyncJsonRpcPeer, JsonRpcCallbacks
from app.application.process_runtime_common import AsyncProcessEntry, BaseProcessRuntime, is_agent_message_item_type


class CodexAppServerRuntime(BaseProcessRuntime):
    def __init__(self, codex_store, log_store, data_dir=None, event_bus=None, processes=None, help_orchestrator=None, refresh_task_result=None):
        super().__init__(
            codex_store,
            log_store,
            data_dir=data_dir,
            event_bus=event_bus,
            processes=processes,
            help_orchestrator=help_orchestrator,
            refresh_task_result=refresh_task_result,
        )
        self._app_server_cmd = self._build_app_server_cmd()
        self._async_clients: dict[str, AppServerClient] = {}
        self._pending_approvals: dict[str, dict] = {}

    def _build_app_server_cmd(self) -> list[str]:
        cmd = shlex.split(os.getenv("CODEX_APP_SERVER_CMD", "codex app-server"))
        if self._command_sets_model(cmd):
            return cmd

        model = os.getenv("CODEX_APP_SERVER_MODEL", "gpt-5.4-mini").strip()
        if model:
            cmd.extend(["-c", f"model={model}"])
        
        # Clean up any existing permission flags to avoid duplicates/conflicts
        cmd = [arg for arg in cmd if not arg.startswith("--permission-mode=")]
        cmd = [arg for arg in cmd if not arg.startswith("--permission-prompt-tool=")]

        # Add correct permission bypass flags for automated background tasks
        cmd.append("--permission-mode=bypassPermissions")
        cmd.append("--permission-prompt-tool=stdio")
            
        return cmd

    @staticmethod
    def _command_sets_model(cmd: list[str]) -> bool:
        for index, arg in enumerate(cmd):
            if arg in {"-c", "--config"}:
                next_arg = cmd[index + 1] if index + 1 < len(cmd) else ""
                if next_arg.split("=", 1)[0] == "model":
                    return True
            if arg.startswith("--config="):
                value = arg.split("=", 1)[1]
                if value.split("=", 1)[0] == "model":
                    return True
        return False

    def check_availability(self) -> bool:
        try:
            return subprocess.run(
                [self._app_server_cmd[0], "--version"],
                capture_output=True,
            ).returncode == 0
        except Exception:
            return False

    async def write_input_async(
        self,
        *,
        workspace_id: str | None = None,
        input_text: str,
        wait: bool = True,
        task_id: str | None = None,
        executor: str = "codex",
        provider: str | None = None,
        model: str | None = None,
        resume_session_id: str | None = None,
        resume_message_id: str | None = None,
        cwd: str | None = None,
        env_overrides: dict[str, str] | None = None,
        command_args: list[str] | None = None,
        force_new_session: bool = False,
        **legacy_kwargs,
    ) -> str:
        workspace_id = self._resolve_workspace_id(workspace_id, **legacy_kwargs)
        process_key = task_id or workspace_id
        entry = self._processes.get(process_key)
        prompt_text = input_text.rstrip("\n")
        evt = asyncio.Event() if wait else None

        if entry is not None and entry.alive:
            self._processes.pop(process_key, None)
            await self._cleanup_entry(process_key, entry)

        entry = await self._spawn_process_async(
            workspace_id=workspace_id,
            resume_session_id=resume_session_id,
            task_id=task_id,
            prompt_text=prompt_text,
            waiter=evt,
            cwd=cwd,
            provider=provider,
            model=model,
            env_overrides=env_overrides,
            command_args=command_args,
            force_new_session=force_new_session,
        )

        await self._append_log(workspace_id, "stdin", prompt_text, task_id)
        if wait and evt:
            try:
                await asyncio.wait_for(evt.wait(), timeout=600)
            except asyncio.TimeoutError:
                return "timeout"
            return "done"

        return "responding"

    async def terminate_task(self, task_id: str):
        # Clean up specific client map
        self._async_clients.pop(task_id, None)
        # Delegate to base for process cleanup
        await super().terminate_task(task_id)

    async def resolve_approval(self, item_id: str, decision: str) -> bool:
        pending = self._pending_approvals.get(item_id)
        if pending is None:
            return False

        task_id = pending.get("task_id")
        workspace_id = pending.get("session_id")
        client = self._async_clients.get(task_id or workspace_id)
        if client is None:
            return False

        success = await client.resolve_pending_request(item_id, decision)
        if success:
            self._pending_approvals.pop(item_id, None)
            if self._event_bus is not None:
                await self._event_bus.append({
                    "type": "approval_resolved",
                    "item_id": item_id,
                    "task_id": task_id,
                    "session_id": workspace_id,
                    "decision": decision,
                    "execution_process_id": pending.get("execution_process_id"),
                })
        return success

    def get_pending_approvals(self) -> dict[str, dict]:
        return self._pending_approvals.copy()

    def _owns_entry(self, entry) -> bool:
        return getattr(entry, "executor", None) == "codex"

    async def _spawn_process_async(
        self,
        workspace_id: str,
        resume_session_id: str | None,
        task_id: str | None,
        prompt_text: str,
        waiter: asyncio.Event | None,
        cwd: str | None,
        provider: str | None = None,
        model: str | None = None,
        env_overrides: dict[str, str] | None = None,
        command_args: list[str] | None = None,
        force_new_session: bool = False,
    ) -> AsyncProcessEntry:
        import sys

        workspace = await self.codex_store.load_codex_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")

        workspace.status = "responding"
        workspace.last_active_at = datetime.now()
        await self.codex_store.save_codex_workspace(workspace)

        if self._event_bus is not None:
            await self._event_bus.append({
                "type": "session_status",
                "session_id": workspace_id,
                "workspace_id": workspace_id,
                "status": "responding",
            })

        effective_cwd = cwd or getattr(workspace, "cwd", None) or self._data_dir
        cmd = list(self._app_server_cmd)

        # Binary path resolution
        for common_path in ["~/.npm-global/bin/codex", "/usr/local/bin/codex", "/opt/homebrew/bin/codex"]:
            expanded = os.path.expanduser(common_path)
            if os.path.exists(expanded):
                cmd[0] = expanded
                break

        env = os.environ.copy()
        paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", os.path.expanduser("~/.npm-global/bin")]
        env["PATH"] = ":".join(paths) + ":" + env.get("PATH", "")

        # Set provider/model env vars if specified
        if provider:
            env["CODEX_APP_SERVER_PROVIDER"] = provider
        if model:
            env["CODEX_APP_SERVER_MODEL"] = model

        # Apply rendered env overrides from runtime catalog templates
        if env_overrides:
            env.update(env_overrides)

        # Append rendered command args from runtime catalog templates
        if command_args:
            cmd.extend(command_args)

        print(f"[DEBUG] spawning async app-server cmd={cmd} cwd={effective_cwd}", file=sys.stderr, flush=True)

        proc = await asyncio.create_subprocess_exec(
            cmd[0],
            *cmd[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=effective_cwd,
            env=env,
        )

        use_auto_approve = os.getenv("CODEX_AUTO_APPROVE", "1") == "1"
        client = AppServerClient(
            codex_store=self.codex_store,
            log_store=self.log_store,
            event_bus=self._event_bus,
            notification_callback=self._make_app_server_notification_callback(workspace_id, task_id),
            auto_approve=use_auto_approve,
        )

        async def on_approval_required(item_id: str, request):
            task = await self.codex_store.load_codex_task(task_id) if task_id else None
            execution_process_id = task.last_execution_process_id if task else None
            self._pending_approvals[item_id] = {
                "task_id": task_id,
                "session_id": workspace_id,
                "method": request.method,
                "params": request.params,
                "item_id": item_id,
                "execution_process_id": execution_process_id,
            }
            if self._event_bus:
                await self._event_bus.append({
                    "type": "approval_required",
                    "item_id": item_id,
                    "method": request.method,
                    "params": request.params,
                    "task_id": task_id,
                    "session_id": workspace_id,
                    "execution_process_id": execution_process_id,
                })

        client.set_approval_callback(on_approval_required)

        entry = AsyncProcessEntry(
            proc=proc,
            output_task=None,
            alive=True,
            session_id=workspace_id,
            task_id=task_id,
            executor="codex",
            cwd=effective_cwd,
            resume_session_id=workspace.thread_id,
            pending_waiters=[waiter] if waiter else [],
        )

        peer = AsyncJsonRpcPeer(
            stdin=proc.stdin,
            stdout=proc.stdout,
            callbacks=JsonRpcCallbacks(on_raw_line=lambda line: self._on_raw_line(workspace_id, line, entry, task_id)),
        )
        client.attach_peer(peer)

        async def handshake():
            try:
                await peer.start()
                await self._append_log(workspace_id, "runtime", "Handshaking...", task_id)
                await client.initialize()
                await client.initialized()
                
                # When force_new_session=True, do NOT fallback to workspace.thread_id
                # When force_new_session=False, use resume_session_id or fallback to workspace.thread_id
                effective_resume_id = resume_session_id if force_new_session else (resume_session_id or workspace.thread_id)

                if effective_resume_id:
                    try:
                        res = await client.thread_fork(effective_resume_id)
                        await self._apply_thread_result(workspace, entry, res, task_id)
                    except Exception as exc:
                        if "no rollout found" in str(exc).lower():
                            res = await client.thread_start()
                            await self._apply_thread_result(workspace, entry, res, task_id)
                        else:
                            raise
                else:
                    res = await client.thread_start()
                    await self._apply_thread_result(workspace, entry, res, task_id)

                if prompt_text:
                    await client.turn_start(prompt_text)
            except Exception as exc:
                print(f"[ERROR] Handshake failed: {exc}", file=sys.stderr)
                entry.had_error = True
                entry.result_text = str(exc)
                await self._append_log(workspace_id, "error", f"Handshake failed: {exc}", task_id)
                if task_id:
                    await self._mark_task_failed(task_id, entry)
                for w in entry.pending_waiters:
                    w.set()
                entry.pending_waiters.clear()
            finally:
                if proc.returncode is not None:
                    entry.alive = False

        entry.output_task = asyncio.create_task(handshake())
        self._processes[task_id or workspace_id] = entry
        self._async_clients[task_id or workspace_id] = client
        return entry

    async def _on_raw_line(self, workspace_id: str, line: str, entry, task_id: str | None):
        await self._append_log(workspace_id, "stdout", line, task_id)
        if entry.alive:
            await self._capture_on_reader(workspace_id, line, entry, task_id)

    async def _apply_thread_result(self, workspace, entry, result: dict, task_id: str | None):
        thread_id = result.get("thread_id") or (result.get("thread", {}).get("id"))
        if thread_id:
            workspace.thread_id = thread_id
            entry.resume_session_id = thread_id
            await self.codex_store.save_codex_workspace(workspace)
            if task_id:
                task = await self.codex_store.load_codex_task(task_id)
                if task:
                    task.resume_session_id = thread_id
                    await self.codex_store.save_codex_task(task)

    def _make_app_server_notification_callback(self, workspace_id: str, task_id: str | None):
        async def callback(method: str, params: dict) -> bool:
            task = await self.codex_store.load_codex_task(task_id) if task_id else None
            execution_process_id = task.last_execution_process_id if task else None

            if method == "error":
                msg = params.get("error", {}).get("message") or str(params)
                entry = self._processes.get(task_id or workspace_id)
                if entry:
                    entry.had_error = True
                    entry.result_text = msg
                    await self._mark_task_failed(task_id, entry)
                    for w in entry.pending_waiters:
                        w.set()
                    entry.pending_waiters.clear()
                return False

            if method in ("turn/completed", "turn.completed"):
                entry = self._processes.get(task_id or workspace_id)
                if entry:
                    status = params.get("status") or params.get("turn", {}).get("status")
                    if str(status).lower() == "failed":
                        error_payload = params.get("error") or params.get("turn", {}).get("error") or {}
                        error_message = None
                        if isinstance(error_payload, dict):
                            error_message = error_payload.get("message") or error_payload.get("detail")
                        if not error_message:
                            error_message = params.get("message") or params.get("detail")
                        entry.had_error = True
                        if isinstance(error_message, str) and error_message.strip():
                            entry.result_text = error_message.strip()
                        await self._mark_task_failed(task_id, entry)
                    else:
                        await self._mark_task_done(task_id, entry)
                    for w in entry.pending_waiters:
                        w.set()
                    entry.pending_waiters.clear()
                return False

            if method in ("item/completed", "item.completed"):
                item = params.get("item", {})
                if is_agent_message_item_type(item.get("type")) and item.get("phase") == "final_answer":
                    text = item.get("text", "").strip()
                    entry = self._processes.get(task_id or workspace_id)
                    if entry:
                        entry.result_text = text
                    if task_id:
                        await self._persist_assistant_message(task_id, execution_process_id, text)
                return False

            # Token-level streaming: codex emits incremental item.delta / item.updated
            # notifications while the agent is generating its final answer. Mirror the
            # Claude path: compute delta vs. last broadcast and emit message_delta.
            if method in ("item/delta", "item.delta", "item/updated", "item.updated"):
                item = params.get("item", {})
                if not is_agent_message_item_type(item.get("type")):
                    return False
                new_text = (item.get("text") or "").strip()
                if not new_text:
                    return False
                entry = self._processes.get(task_id or workspace_id)
                if entry is None or new_text == entry.last_emitted_assistant_text:
                    return False
                last = entry.last_emitted_assistant_text
                delta = new_text[len(last):] if new_text.startswith(last) else new_text
                if delta:
                    entry.delta_seq += 1
                    entry.last_emitted_assistant_text = new_text
                    await self._emit_message_delta(workspace_id, task_id, entry.delta_seq, delta)
                return False

            return False
        return callback
