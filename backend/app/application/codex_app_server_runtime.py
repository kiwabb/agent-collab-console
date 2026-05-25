import asyncio
import json
import logging
import os
import shlex
import subprocess
import time
from datetime import datetime

from app.application.json_rpc_client import AppServerClient, AsyncJsonRpcPeer, JsonRpcCallbacks
from app.application.process_runtime_common import AsyncProcessEntry, BaseProcessRuntime, is_agent_message_item_type


logger = logging.getLogger(__name__)


# Total turn budget. Even a healthy Engineer/QA pass should fit comfortably
# in this. Bumped 600 → 480 to fail faster than the absurd default; keep
# overridable via env for slow runners.
CODEX_TURN_TIMEOUT_S = int(os.getenv("CODEX_TURN_TIMEOUT_S", "480"))
# Idle (stdout-silence) timeout. Catches the failure mode where the Codex
# app server stops streaming after a tool_use but never feeds the tool
# result back into the model — the total-turn timeout alone would let the
# graph wait the full budget for nothing.
CODEX_IDLE_TIMEOUT_S = int(os.getenv("CODEX_IDLE_TIMEOUT_S", "180"))


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

        # `codex app-server` does NOT accept --permission-mode / --permission-prompt-tool
        # (it exits with "unexpected argument", code 2, before the JSON-RPC handshake —
        # which manifests downstream as "Connection lost" on every send and a 900s
        # dispatch timeout). Permission handling is done over the protocol instead:
        # AppServerClient._on_server_request auto-approves file-change / command-exec
        # requests. So strip any such flags that leak in from CODEX_APP_SERVER_CMD and
        # never add them here.
        cmd = [arg for arg in cmd if not arg.startswith("--permission-mode")]
        cmd = [arg for arg in cmd if not arg.startswith("--permission-prompt-tool")]

        # Grant the automated agent full, non-interactive workspace access. Under
        # codex's restrictive default sandbox + approval policy it cannot write the
        # git index lock (a git worktree's git metadata lives in the MAIN repo's
        # .git/worktrees/<id>/, outside the sandboxed workspace) and it stalls on
        # command-execution approval requests (activeFlags=['waitingOnApproval']).
        # These `-c` configs are the codex-app-server-correct equivalent of the old
        # (invalid) --permission-mode=bypassPermissions flag.
        if not self._config_sets(cmd, "approval_policy"):
            cmd.extend(["-c", 'approval_policy="never"'])
        if not self._config_sets(cmd, "sandbox_mode"):
            cmd.extend(["-c", 'sandbox_mode="danger-full-access"'])

        return cmd

    @staticmethod
    def _config_sets(cmd: list[str], key: str) -> bool:
        for index, arg in enumerate(cmd):
            if arg in {"-c", "--config"} and index + 1 < len(cmd):
                if cmd[index + 1].split("=", 1)[0].strip() == key:
                    return True
            if arg.startswith("--config=") and arg.split("=", 1)[1].split("=", 1)[0].strip() == key:
                return True
        return False

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

    @staticmethod
    def _with_model_override(cmd: list[str], model: str) -> list[str]:
        """Return cmd with the codex `-c model=...` config set to `model`.

        The base cmd is built once at construction with a default model, but each
        task can select a different model. The codex CLI honours the `-c model=`
        flag (not the CODEX_APP_SERVER_MODEL env var), so the per-task model must
        rewrite the flag here or the app-server silently runs the wrong model —
        which can leave the turn hanging until the 900s dispatch timeout.
        """
        result = list(cmd)
        for index, arg in enumerate(result):
            if arg in {"-c", "--config"} and index + 1 < len(result):
                if result[index + 1].split("=", 1)[0] == "model":
                    result[index + 1] = f"model={model}"
                    return result
            if arg.startswith("--config=") and arg.split("=", 1)[1].split("=", 1)[0] == "model":
                result[index] = f"--config=model={model}"
                return result
        result.extend(["-c", f"model={model}"])
        return result

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
        # Seed the idle clock so the watchdog has a starting reference.
        entry.last_event_at = time.monotonic()

        if wait and evt:
            # Total-turn deadline + idle-stdout deadline. Whichever trips first
            # aborts the task, so a stuck tool-result loop fails in 3 min
            # instead of hanging the full 8-min budget.
            try:
                await asyncio.wait_for(
                    self._wait_with_idle_watchdog(evt, entry),
                    timeout=CODEX_TURN_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "codex turn exceeded total budget %ss for task=%s",
                    CODEX_TURN_TIMEOUT_S, task_id,
                )
                await self._abort_for_timeout(task_id, entry, reason="turn_timeout")
                return "timeout"
            if entry.had_error:
                return "timeout" if getattr(entry, "_timeout_reason", None) else "failed"
            return "done"

        return "responding"

    async def _wait_with_idle_watchdog(self, evt: asyncio.Event, entry: AsyncProcessEntry) -> None:
        """Resolve when the turn completes OR when stdout has been silent
        for CODEX_IDLE_TIMEOUT_S — whichever first."""
        while not evt.is_set():
            try:
                await asyncio.wait_for(evt.wait(), timeout=15)
                return
            except asyncio.TimeoutError:
                idle_for = time.monotonic() - (entry.last_event_at or time.monotonic())
                if idle_for >= CODEX_IDLE_TIMEOUT_S:
                    logger.warning(
                        "codex turn idle %.0fs (threshold %ss) — aborting",
                        idle_for, CODEX_IDLE_TIMEOUT_S,
                    )
                    return  # caller will see evt not set + had_error set
            # else: loop and re-check both signals

    async def _abort_for_timeout(self, task_id: str | None, entry: AsyncProcessEntry, *, reason: str) -> None:
        """Mark the task failed and kill the subprocess so downstream
        rework / replan logic fires immediately."""
        entry.had_error = True
        entry._timeout_reason = reason
        msg = (
            "Codex turn aborted by framework: "
            f"{reason} (idle threshold {CODEX_IDLE_TIMEOUT_S}s, total budget {CODEX_TURN_TIMEOUT_S}s). "
            "The CLI stopped streaming events — most likely the tool-result loop hung."
        )
        if not entry.result_text:
            entry.result_text = msg
        try:
            await self._mark_task_failed(task_id, entry)
        except Exception:  # noqa: BLE001
            pass
        # Drop the subprocess so the next dispatch can spawn a fresh one.
        try:
            await self.terminate_task(task_id) if task_id else None
        except Exception:  # noqa: BLE001
            pass

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
        # Per-task model: rewrite the baked-in `-c model=` flag so the selected
        # model actually reaches the codex CLI (the env var below is not enough).
        if model:
            cmd = self._with_model_override(cmd, model)

        # Binary path resolution
        for common_path in ["~/.npm-global/bin/codex", "/usr/local/bin/codex", "/opt/homebrew/bin/codex"]:
            expanded = os.path.expanduser(common_path)
            if os.path.exists(expanded):
                cmd[0] = expanded
                break

        env = os.environ.copy()
        # APPEND fallback dirs (don't prepend): the inherited PATH already points at
        # the working toolchain (e.g. node@24). Prepending /opt/homebrew/bin ahead of
        # it can shadow that with a broken Homebrew `node` (codex is a Node script, so
        # the wrong node makes the app-server crash on startup → "Connection lost" →
        # 900s dispatch timeout). Fallback dirs only fill gaps when PATH lacks them.
        paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", os.path.expanduser("~/.npm-global/bin")]
        existing_path = env.get("PATH", "")
        env["PATH"] = (existing_path + ":" + ":".join(paths)) if existing_path else ":".join(paths)

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

        logger.debug("spawning async app-server cmd=%s cwd=%s", cmd, effective_cwd)

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
                logger.error("Handshake failed: %s", exc)
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
        # Update idle-watchdog clock: every raw line counts as activity, so
        # a healthy stream of tool_use / delta / item events keeps the task
        # alive even on a long generation; only true stdout silence trips.
        entry.last_event_at = time.monotonic()
        # Feed the GLOBAL stall watchdog too. codex frames are JSON-RPC
        # notifications ({"method":"item/...",...}) with no top-level "type",
        # so the base reader's _capture_on_reader returns before its
        # stream_event branch ever calls task_activity.touch(). Without this,
        # the stall watchdog only sees the one touch at task start and kills
        # every codex task at the stall threshold — even mid-stream — which
        # then leaves a stray result and makes the Conductor see empty failures.
        if task_id:
            from app.application import task_activity
            task_activity.touch(task_id)
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

    _TOOL_ITEM_TYPES = {
        "command_execution",
        "commandexecution",
        "file_change",
        "filechange",
        "mcp_tool_call",
        "mcptoolcall",
        "web_search",
        "websearch",
    }

    @classmethod
    def _is_tool_item(cls, item_type: str | None) -> bool:
        if not item_type:
            return False
        normalized = str(item_type).strip().lower().replace("-", "_").replace(" ", "_")
        return normalized in cls._TOOL_ITEM_TYPES

    @staticmethod
    def _normalize_tool_item_type(item_type: str | None) -> str:
        return str(item_type or "").strip().lower().replace("-", "_").replace(" ", "_")

    async def _emit_tool_event(self, workspace_id: str, task_id: str | None, payload: dict):
        await self._append_log(
            workspace_id,
            "tool_event",
            json.dumps(payload, ensure_ascii=False, default=str),
            task_id,
        )

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

            if method in ("item/started", "item.started"):
                item = params.get("item", {})
                if self._is_tool_item(item.get("type")):
                    entry = self._processes.get(task_id or workspace_id)
                    item_id = item.get("id") or ""
                    if entry is not None and item_id:
                        entry.tool_item_started_at[item_id] = datetime.now()
                    await self._emit_tool_event(workspace_id, task_id, {
                        "kind": "tool_started",
                        "tool_use_id": item_id,
                        "item_type": self._normalize_tool_item_type(item.get("type")),
                        "tool_name": item.get("name") or item.get("tool_name") or "",
                        "command": item.get("command"),
                        "file_path": item.get("path") or item.get("file_path"),
                        "input": item.get("input") or item.get("arguments") or {},
                    })
                return False

            if method in ("item/completed", "item.completed"):
                item = params.get("item", {})
                if is_agent_message_item_type(item.get("type")):
                    # codex 0.132.0 tags agent messages with phase "commentary"/
                    # "final_answer" (older builds only emitted "final_answer").
                    # Capture the latest agent message text as the result — the
                    # final one wins — so the engineer's answer is never lost just
                    # because the phase label changed across CLI versions.
                    text = (item.get("text") or "").strip()
                    if text:
                        entry = self._processes.get(task_id or workspace_id)
                        if entry:
                            entry.result_text = text
                        if task_id and item.get("phase") in (None, "final_answer"):
                            await self._persist_assistant_message(task_id, execution_process_id, text)
                    return False
                if self._is_tool_item(item.get("type")):
                    entry = self._processes.get(task_id or workspace_id)
                    item_id = item.get("id") or ""
                    duration_ms = None
                    if entry is not None and item_id:
                        started = entry.tool_item_started_at.pop(item_id, None)
                        if started is not None:
                            duration_ms = int((datetime.now() - started).total_seconds() * 1000)
                    exit_code = item.get("exit_code")
                    is_error = False
                    status_value = str(item.get("status") or "").lower()
                    if status_value in {"failed", "error", "cancelled", "canceled", "aborted", "timeout"}:
                        is_error = True
                    if isinstance(exit_code, int) and exit_code != 0:
                        is_error = True
                    await self._emit_tool_event(workspace_id, task_id, {
                        "kind": "tool_completed",
                        "tool_use_id": item_id,
                        "item_type": self._normalize_tool_item_type(item.get("type")),
                        "tool_name": item.get("name") or item.get("tool_name") or "",
                        "command": item.get("command"),
                        "file_path": item.get("path") or item.get("file_path"),
                        "input": item.get("input") or item.get("arguments") or {},
                        "output": item.get("aggregated_output") or item.get("output") or item.get("result") or "",
                        "exit_code": exit_code,
                        "is_error": is_error,
                        "status": item.get("status"),
                        "duration_ms": duration_ms,
                    })
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
