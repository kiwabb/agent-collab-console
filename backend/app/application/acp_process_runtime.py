"""ACP v1 process runtime — a :class:`BaseProcessRuntime` sibling.

Spawns a local ACP agent subprocess (no shell), runs the stable-v1 wire
lifecycle through :class:`AcpClient`, and maps ACP session updates into the
existing task message / log / WebSocket / trace / ExecutionProcess lifecycle.

Each turn spawns a fresh process and a fresh ACP session (MVP — no cross-turn
session reuse). The runtime loads its :class:`AcpRuntimeConfig` from the runtime
catalog at the process boundary using the task's executor id (the catalog
service stores the resolved ACP executor id on ``task.executor``).

Security (fail-closed):
- ``create_subprocess_exec(command, *args)`` — never a shell, ``start_new_session=True``.
- env = small base + only the allowlisted host variable names; a missing
  allowlisted variable rejects launch (never silently inherits the value).
- No env value is ever persisted or returned — only names are stored.
- No auto-approval; permission timeout resolves as ``cancelled``; protocol
  errors / handshake failure / process exit / turn timeout all fail the task
  and terminalize its ExecutionProcess.
- The ACP session id lives on ``task.resume_session_id`` only — never on the
  shared workspace thread pointers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime

from app.adapters.local_process import run_trusted_local
from app.application import timeouts
from app.application.acp_client import (
    ACP_STOP_REASON_END_TURN,
    AcpClient,
    AcpClosedCallback,
    AcpNotificationCallback,
    AcpPermissionCallback,
    AcpPermissionRequest,
    AcpProtocolError,
)
from app.application.json_rpc_client import AsyncJsonRpcPeer, JsonObject
from app.application.process_runtime_common import (
    AsyncProcessEntry,
    BaseProcessRuntime,
    RefreshTaskResult,
    RuntimeCodexStore,
    RuntimeEventBus,
    RuntimeHelpOrchestrator,
    RuntimeLogStore,
)
from app.domain.models import CodexTask, RuntimeCatalog

logger = logging.getLogger(__name__)

#: Small base environment inherited by every ACP agent. Only well-known,
#: non-secret PATH/ locale / runtime knobs — no credentials. Allowlisted host
#: variables are layered on top in :meth:`_build_env`.
_BASE_ENV_KEYS = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR")


#: Callable that returns the live runtime catalog. Injected at construction so
#: the runtime can resolve an :class:`AcpRuntimeConfig` by executor id without
#: depending on a specific store implementation.
CatalogLoader = Callable[[], Awaitable[RuntimeCatalog]]


class AcpProcessRuntime(BaseProcessRuntime):
    """Runtime adapter for a local ACP v1 stdio agent."""

    def __init__(
        self,
        codex_store: RuntimeCodexStore,
        log_store: RuntimeLogStore,
        catalog_loader: CatalogLoader,
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
        self._catalog_loader = catalog_loader
        # task_id -> AcpClient for the live turn (one client per turn in MVP).
        self._acp_clients: dict[str, AcpClient] = {}
        # item_id (request_id str) -> pending permission metadata, shared with
        # the manager aggregation the same way Codex's _pending_approvals is.
        self._pending_approvals: dict[str, dict[str, object]] = {}

    # --- ownership / availability -------------------------------------

    def _owns_entry(self, entry: AsyncProcessEntry) -> bool:
        return getattr(entry, "executor", None) == "acp"

    def check_availability(self, executor_id: str | None = None) -> bool:
        """Probe ``command --version`` for the configured ACP executor.

        Without an executor id (e.g. a generic manager availability check) this
        conservatively reports ``False`` — ACP availability is per-executor.
        """
        if executor_id is None:
            return False
        config = self._load_acp_config_sync(executor_id)
        if config is None:
            return False
        try:
            return (
                run_trusted_local(
                    [config.command, "--version"],
                    capture_output=True,
                ).returncode
                == 0
            )
        except Exception:
            return False

    # --- connectivity probe (ACP initialize handshake) ----------------

    async def probe_connectivity(
        self, executor_id: str
    ) -> tuple[bool, str, float]:
        """Run a real ACP ``initialize`` handshake against the configured agent.

        Spawns the executor's ``command args``, negotiates protocol version 1,
        and tears the process down immediately. Returns ``(success, error,
        latency_ms)``. ``error`` is empty on success. Used by the
        ``/runtime-catalog/test-acp`` endpoint so users can verify an ACP
        executor is actually wire-reachable, not just that the binary exists.

        Fail-closed: missing allowlisted env, handshake timeout, protocol
        mismatch, and early process exit all report ``success=False`` with an
        actionable message. Env values are never returned.
        """
        import time as _time

        config, executor_config = await self._load_acp_config(executor_id)
        if executor_config is None or config is None:
            return False, f"ACP executor '{executor_id}' not found or has no ACP config", 0
        try:
            env = self._build_env(config)
        except RuntimeError as exc:
            return False, str(exc), 0

        cmd = [config.command, *config.args]
        started = _time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                cmd[0],
                *cmd[1:],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
                limit=4 * 1024 * 1024,
            )
        except FileNotFoundError:
            return False, f"ACP command not found: {config.command}", 0
        except OSError as exc:
            return False, f"ACP launch failed: {exc}", 0

        if proc.stdin is None or proc.stdout is None:
            await self._kill_process_tree(proc)
            return False, "ACP agent subprocess did not expose stdin/stdout pipes", 0

        peer = AsyncJsonRpcPeer(stdin=proc.stdin, stdout=proc.stdout)
        client = AcpClient(
            peer,
            on_session_update=None,
            on_permission_request=None,
            on_closed=None,
        )
        client.set_handshake_timeout(timeouts.acp_handshake_timeout_s())

        error = ""
        success = False
        try:
            await peer.start()
            await client.initialize()
            success = True
        except AcpProtocolError as exc:
            error = f"ACP protocol error: {exc}"
        except TimeoutError:
            error = f"ACP initialize handshake timed out (>{timeouts.acp_handshake_timeout_s()}s)"
        except RuntimeError as exc:
            error = str(exc)
        except Exception as exc:
            error = f"ACP probe failed: {exc}"
        finally:
            await self._kill_process_tree(proc)
            with suppress(Exception):
                await peer.stop()

        latency_ms = round((_time.monotonic() - started) * 1000, 1)
        return success, error, latency_ms

    async def _kill_process_tree(self, proc: asyncio.subprocess.Process) -> None:
        """Best-effort terminate of a probe subprocess (SIGTERM -> kill)."""
        with suppress(Exception):
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()

    # --- public entrypoint --------------------------------------------

    async def write_input_async(
        self,
        *,
        workspace_id: str | None = None,
        input_text: str,
        wait: bool = True,
        task_id: str | None = None,
        executor: str = "acp",
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
            model=model,
        )

        await self._append_log(workspace_id, "stdin", prompt_text, task_id)
        entry.last_event_at = time.monotonic()

        if wait and evt:
            turn_timeout = timeouts.acp_turn_timeout_s()
            try:
                await asyncio.wait_for(
                    self._wait_with_idle_watchdog(evt, entry),
                    timeout=turn_timeout,
                )
            except asyncio.TimeoutError:  # noqa: UP041
                logger.warning(
                    "acp turn exceeded total budget %ss for task=%s",
                    turn_timeout,
                    task_id,
                )
                await self._abort_for_timeout(task_id, entry, reason="turn_timeout")
                return "timeout"
            if entry.had_error:
                return "timeout" if entry.timeout_reason else "failed"
            if not evt.is_set():
                await self._abort_for_timeout(task_id, entry, reason="idle_timeout")
                return "timeout"
            return "done"

        if task_id:
            entry.turn_watchdog_task = asyncio.create_task(
                self._fire_and_forget_turn_watchdog(task_id, entry),
                name=f"acp-turn-watchdog-{task_id}",
            )
        return "responding"

    async def _wait_with_idle_watchdog(
        self, evt: asyncio.Event, entry: AsyncProcessEntry
    ) -> None:
        """Resolve when the turn completes OR stdout/IPC has been silent for
        ``CODEX_IDLE_TIMEOUT_S`` — reusing the same threshold as the codex
        runtime so a stuck tool-result loop fails fast."""
        idle_threshold = timeouts.codex_idle_timeout_s()
        while not evt.is_set():
            try:
                await asyncio.wait_for(evt.wait(), timeout=15)
                return
            except asyncio.TimeoutError:  # noqa: UP041
                idle_for = time.monotonic() - (entry.last_event_at or time.monotonic())
                if idle_for >= idle_threshold:
                    logger.warning(
                        "acp turn idle %.0fs (threshold %ss) — aborting",
                        idle_for,
                        idle_threshold,
                    )
                    return

    async def _fire_and_forget_turn_watchdog(
        self, task_id: str, entry: AsyncProcessEntry
    ) -> None:
        start = time.monotonic()
        turn_timeout = timeouts.acp_turn_timeout_s()
        idle_threshold = timeouts.codex_idle_timeout_s()
        while entry.alive:
            try:
                await asyncio.sleep(15)
                task = await self.codex_store.load_codex_task(task_id)
                if task is not None and _is_terminal(task.status):
                    return
                elapsed = time.monotonic() - start
                if elapsed >= turn_timeout:
                    logger.warning(
                        "acp fire-and-forget turn exceeded total budget %ss for task=%s",
                        turn_timeout,
                        task_id,
                    )
                    await self._abort_for_timeout(task_id, entry, reason="turn_timeout")
                    return
                idle_for = time.monotonic() - (entry.last_event_at or time.monotonic())
                if idle_for >= idle_threshold:
                    logger.warning(
                        "acp fire-and-forget turn idle %.0fs (threshold %ss) for task=%s",
                        idle_for,
                        idle_threshold,
                        task_id,
                    )
                    await self._abort_for_timeout(task_id, entry, reason="idle_timeout")
                    return
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("acp fire-and-forget watchdog failed task=%s: %s", task_id, exc)
                return

    async def _abort_for_timeout(
        self, task_id: str | None, entry: AsyncProcessEntry, *, reason: str
    ) -> None:
        """Fail the task, cancel the ACP session, and drop the subprocess."""
        entry.had_error = True
        entry.timeout_reason = reason
        msg = (
            "ACP turn aborted by framework: "
            f"{reason} (idle threshold {timeouts.codex_idle_timeout_s()}s, "
            f"total budget {timeouts.acp_turn_timeout_s()}s). "
            "The agent stopped streaming session updates — likely a hung tool loop."
        )
        if not entry.result_text:
            entry.result_text = msg
        # Best-effort: tell the agent to cancel the turn before we tear down.
        if task_id:
            client = self._acp_clients.get(task_id)
            if client is not None:
                with suppress(Exception):
                    await client.cancel()
        if task_id:
            try:
                await self._mark_task_failed(task_id, entry)
            except Exception:
                logger.debug("acp timeout task failure marking failed: task_id=%s", task_id, exc_info=True)
        try:
            if task_id:
                await self.terminate_task(task_id)
        except Exception:
            logger.debug("acp timeout process termination failed: task_id=%s", task_id, exc_info=True)

    # --- catalog resolution -------------------------------------------

    async def _load_acp_config(self, executor_id: str):
        """Load the :class:`AcpRuntimeConfig` for an executor id."""
        catalog = await self._catalog_loader()
        for executor in catalog.executors:
            if executor.id == executor_id and executor.executor_type == "acp":
                if executor.acp is None:
                    return None, executor
                return executor.acp, executor
        return None, None

    def _load_acp_config_sync(self, executor_id: str):
        """Sync best-effort config lookup for the availability probe.

        Runs the async loader in a fresh event loop. Only used by
        :meth:`check_availability` which is itself a sync probe.
        """
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._load_acp_config(executor_id))
            finally:
                loop.close()
        except Exception:
            return None, None

    def _build_env(self, config) -> dict[str, str]:
        """Build a small base env + allowlisted host variables.

        Missing allowlisted variables reject launch (fail-closed) — the agent
        must not silently run without a variable its config promised it would
        receive. Credential values are read from the process env and never
        stored or returned.
        """
        env: dict[str, str] = {}
        for key in _BASE_ENV_KEYS:
            value = os.environ.get(key)
            if value:
                env[key] = value
        # Provide a minimal PATH fallback if the host env lacks one (rare, but
        # keeps the agent's own binary resolvable when command is a bare name).
        if "PATH" not in env:
            env["PATH"] = os.defpath
        missing: list[str] = []
        for name in config.env_allowlist:
            value = os.environ.get(name)
            if value is None:
                missing.append(name)
                continue
            env[name] = value
        if missing:
            raise RuntimeError(
                "ACP launch refused: allowlisted environment variables are not "
                f"set on the backend process: {missing}"
            )
        return env

    # --- spawn ---------------------------------------------------------

    async def _spawn_process_async(
        self,
        workspace_id: str,
        resume_session_id: str | None,
        task_id: str | None,
        prompt_text: str,
        waiter: asyncio.Event | None,
        cwd: str | None,
        model: str | None = None,
    ) -> AsyncProcessEntry:
        workspace = await self.codex_store.load_codex_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")

        task = await self.codex_store.load_codex_task(task_id) if task_id else None
        # Issue tasks must run in their isolated worktree, never fall back to
        # workspace.cwd (= main project repo). Same rule as the claude/codex
        # runtimes.
        task_issue_id = getattr(task, "issue_id", None) if task is not None else None
        if task_issue_id and not cwd:
            raise ValueError(
                f"Issue task {task_id} (issue={task_issue_id}) has no worktree cwd. "
                "Refusing to run in main project directory."
            )
        effective_cwd = cwd or getattr(workspace, "cwd", None) or self._data_dir

        # Resolve the ACP launch config from the runtime catalog. The conductor
        # runner stores the resolved ACP executor id on task.executor, so we
        # read it back here rather than threading a separate parameter through.
        executor_id = getattr(task, "executor", None) if task is not None else None
        if not executor_id:
            raise RuntimeError(
                "ACP launch refused: task has no executor id to resolve its "
                "ACP launch configuration"
            )
        config, _executor_config = await self._load_acp_config(executor_id)
        if config is None:
            raise RuntimeError(
                f"ACP launch refused: executor '{executor_id}' has no ACP launch "
                "configuration in the runtime catalog"
            )

        env = self._build_env(config)

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

        cmd = [config.command, *config.args]
        logger.debug("spawning acp agent cmd=%s cwd=%s", cmd, effective_cwd)

        proc = await asyncio.create_subprocess_exec(
            cmd[0],
            *cmd[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=effective_cwd,
            env=env,
            start_new_session=True,
            limit=4 * 1024 * 1024,
        )
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("ACP agent subprocess did not expose stdin/stdout pipes")

        entry = AsyncProcessEntry(
            proc=proc,
            output_task=None,
            alive=True,
            session_id=workspace_id,
            task_id=task_id,
            executor="acp",
            cwd=effective_cwd,
            resume_session_id=resume_session_id,
            pending_waiters=[waiter] if waiter else [],
            max_timeout_seconds=timeouts.acp_turn_timeout_s(),
        )
        # ACP-specific per-entry state.
        entry._pending_permissions = {}  # type: ignore[attr-defined]
        entry._acp_client = None  # type: ignore[attr-defined]

        async def on_raw_line(line: str) -> None:
            entry.last_event_at = time.monotonic()
            if task_id:
                from app.application import task_activity

                task_activity.touch(task_id)
            await self._append_log(workspace_id, "stdout", line, task_id)

        peer = AsyncJsonRpcPeer(
            stdin=proc.stdin,
            stdout=proc.stdout,
        )
        # Inject our raw-line logger before attaching the AcpClient so the
        # client's callback routing still sees the same peer.
        peer._callbacks.on_raw_line = on_raw_line

        client = AcpClient(
            peer,
            on_session_update=self._make_session_update_callback(workspace_id, task_id, entry),
            on_permission_request=self._make_permission_callback(workspace_id, task_id, entry),
            on_closed=self._make_closed_callback(workspace_id, task_id, entry),
        )
        client.set_handshake_timeout(timeouts.acp_handshake_timeout_s())
        entry._acp_client = client  # type: ignore[attr-defined]

        async def handshake_and_turn() -> None:
            try:
                await peer.start()
                await self._append_log(workspace_id, "runtime", "Handshaking ACP...", task_id)
                await self._initialize_or_fail_fast(client, proc, workspace_id, task_id)
                session_id = await client.session_new()
                entry.resume_session_id = session_id
                # Only persist the ACP session id on the task — never on the
                # shared workspace thread pointers.
                if task_id:
                    t = await self.codex_store.load_codex_task(task_id)
                    if t is not None:
                        t.resume_session_id = session_id
                        await self.codex_store.save_codex_task(t)

                # Optional model config option: only apply if the agent exposed
                # a matching option (never claim an unapplied override).
                if config.model_config_id and model:
                    with suppress(Exception):
                        await client.set_config_option(config.model_config_id, model)

                if prompt_text:
                    stop_reason = await client.session_prompt(
                        prompt_text, timeout=timeouts.acp_turn_timeout_s()
                    )
                    # If the framework already aborted this turn (timeout /
                    # cancel set entry.had_error), do not overwrite the failed
                    # state with a success mark even if a late end_turn arrives.
                    if stop_reason == ACP_STOP_REASON_END_TURN and not entry.had_error:
                        if task_id:
                            await self._mark_task_done(task_id, entry)
                    else:
                        entry.had_error = True
                        if not entry.result_text:
                            entry.result_text = (
                                f"ACP session/prompt ended with stopReason={stop_reason!r}; "
                                "only 'end_turn' is treated as success."
                            )
                        if task_id:
                            await self._mark_task_failed(task_id, entry)
            except AcpProtocolError as exc:
                logger.error("ACP protocol error: %s", exc)
                entry.had_error = True
                entry.result_text = f"ACP protocol error: {exc}"
                await self._append_log(workspace_id, "error", f"ACP protocol error: {exc}", task_id)
                if task_id:
                    await self._mark_task_failed(task_id, entry)
            except Exception as exc:
                logger.error("ACP handshake/turn failed: %s", exc)
                entry.had_error = True
                entry.result_text = str(exc)
                await self._append_log(workspace_id, "error", f"ACP turn failed: {exc}", task_id)
                if task_id:
                    await self._mark_task_failed(task_id, entry)
            finally:
                if proc.returncode is not None:
                    entry.alive = False
                for w in entry.pending_waiters:
                    w.set()
                entry.pending_waiters.clear()

        entry.output_task = asyncio.create_task(handshake_and_turn())
        self._processes[task_id or workspace_id] = entry
        if task_id:
            self._acp_clients[task_id] = client
        return entry

    async def _initialize_or_fail_fast(
        self,
        client: AcpClient,
        proc: asyncio.subprocess.Process,
        workspace_id: str,
        task_id: str | None,
    ) -> None:
        """Race the ACP initialize handshake against process exit + a hard
        bound so a broken agent binary never hangs the full turn budget."""

        async def _do_init() -> None:
            await client.initialize()

        init_task = asyncio.ensure_future(_do_init())
        exit_task = asyncio.ensure_future(proc.wait())
        try:
            done, _pending = await asyncio.wait(
                {init_task, exit_task},
                timeout=timeouts.acp_handshake_timeout_s(),
                return_when=asyncio.FIRST_COMPLETED,
            )
        except Exception:
            init_task.cancel()
            exit_task.cancel()
            raise

        if init_task in done:
            exit_task.cancel()
            init_task.result()  # propagate any handshake exception
            return

        init_task.cancel()
        exit_task.cancel()
        reason = "exited" if proc.returncode is not None else "handshake_timeout"
        stderr_text = await self._drain_stderr(proc)
        await self._emit_executor_failed_to_start(
            workspace_id, task_id, reason=reason, returncode=proc.returncode, stderr=stderr_text
        )
        raise RuntimeError(
            f"ACP agent failed to start ({reason}, rc={proc.returncode}): "
            f"{(stderr_text or '').strip()[:300]}"
        )

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> str:
        if proc.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(proc.stderr.read(4096), timeout=1.0)
            return data.decode("utf-8", "replace") if data else ""
        except Exception:
            return ""

    async def _emit_executor_failed_to_start(
        self,
        workspace_id: str,
        task_id: str | None,
        *,
        reason: str,
        returncode: int | None,
        stderr: str,
    ) -> None:
        logger.error(
            "acp executor failed to start (task=%s reason=%s rc=%s): %s",
            task_id,
            reason,
            returncode,
            (stderr or "").strip()[:300],
        )
        if self._event_bus is None:
            return
        with suppress(Exception):
            await self._event_bus.append(
                {
                    "type": "executor_failed_to_start",
                    "task_id": task_id,
                    "session_id": workspace_id,
                    "executor": "acp",
                    "reason": reason,
                    "returncode": returncode,
                    "stderr": (stderr or "").strip()[:1000],
                }
            )

    # --- session/update + permission translation ----------------------

    def _make_session_update_callback(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
    ) -> AcpNotificationCallback:
        async def callback(update: JsonObject) -> None:
            await self._handle_session_update(workspace_id, task_id, entry, update)

        return callback

    async def _handle_session_update(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
        update: JsonObject,
    ) -> None:
        kind = str(update.get("kind") or update.get("type") or "").strip().lower()
        if kind == "message":
            await self._handle_message_update(workspace_id, task_id, entry, update)
        elif kind == "thought":
            thought = update.get("thought") or update.get("text") or ""
            if isinstance(thought, str) and thought:
                payload = json.dumps({"text": thought}, ensure_ascii=False, default=str)
                await self._append_log(workspace_id, "thinking", payload, task_id)
                entry.last_activity_kind = "reasoning"
        elif kind == "tool":
            await self._handle_tool_update(workspace_id, task_id, entry, update)
        elif kind == "plan":
            payload = json.dumps(update, ensure_ascii=False, default=str)
            await self._append_log(workspace_id, "plan", payload, task_id)
        elif kind == "usage":
            await self._maybe_persist_usage(task_id, update)
            payload = json.dumps(update, ensure_ascii=False, default=str)
            await self._append_log(workspace_id, "usage", payload, task_id)
        else:
            # Unknown update kind: log it raw so nothing is silently dropped.
            payload = json.dumps(update, ensure_ascii=False, default=str)
            await self._append_log(workspace_id, "stdout", payload, task_id)

    async def _handle_message_update(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
        update: JsonObject,
    ) -> None:
        # ACP message updates carry a `content` array of role/content parts,
        # and optional partial/streaming flags. Capture assistant text as the
        # running result and emit deltas against the last broadcast.
        role = str(update.get("role") or "").strip().lower()
        content = update.get("content")
        text_parts: list[str] = []
        if isinstance(content, list):
            for raw_item in content:
                item = raw_item if isinstance(raw_item, dict) else {}
                if str(item.get("type", "")).lower() not in ("", "text"):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        elif isinstance(content, str):
            text_parts.append(content)

        new_text = "".join(text_parts).strip()
        if role in ("", "assistant") and new_text:
            # Persist the latest assistant text as the candidate result.
            from app.application.process_runtime_common import is_cli_control_payload

            if not is_cli_control_payload(new_text):
                entry.result_text = new_text
                entry.produced_real_turn = True
            # Stream deltas to clients.
            if new_text != entry.last_emitted_assistant_text:
                last = entry.last_emitted_assistant_text
                delta = new_text[len(last):] if new_text.startswith(last) else new_text
                if delta:
                    entry.delta_seq += 1
                    entry.last_emitted_assistant_text = new_text
                    await self._emit_message_delta(
                        workspace_id, task_id, entry.delta_seq, delta
                    )
            entry.last_activity_kind = "text"
        elif new_text:
            payload = json.dumps(
                {"role": role, "text": new_text}, ensure_ascii=False, default=str
            )
            await self._append_log(workspace_id, "stdout", payload, task_id)

    async def _handle_tool_update(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
        update: JsonObject,
    ) -> None:
        tool_name = str(update.get("name") or update.get("toolName") or "")
        tool_use_id = str(update.get("id") or update.get("toolUseId") or "")
        state = str(update.get("state") or update.get("status") or "").lower()
        if tool_use_id and tool_use_id in entry.emitted_tool_use_ids and state in ("", "running"):
            return
        if tool_use_id:
            entry.emitted_tool_use_ids.add(tool_use_id)
        payload_obj: JsonObject = {
            "kind": "tool_use",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "state": state,
            "input": update.get("input") or update.get("arguments") or {},
        }
        if "output" in update or "result" in update:
            payload_obj["output"] = update.get("output") or update.get("result")
        if "is_error" in update:
            payload_obj["is_error"] = bool(update.get("is_error"))
        await self._append_log(
            workspace_id,
            "tool_use",
            json.dumps(payload_obj, ensure_ascii=False, default=str),
            task_id,
        )
        entry.last_activity_kind = "tool"
        await self._maybe_emit_worktree_dirty(workspace_id, task_id, entry, tool_name)

    def _make_permission_callback(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
    ) -> AcpPermissionCallback:
        async def callback(request: AcpPermissionRequest) -> None:
            await self._on_permission_request(workspace_id, task_id, entry, request)

        return callback

    async def _on_permission_request(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
        request: AcpPermissionRequest,
    ) -> None:
        item_id = str(request.request_id)
        task = await self.codex_store.load_codex_task(task_id) if task_id else None
        execution_process_id = task.last_execution_process_id if task else None
        permissions: dict[str, dict[str, object]] = getattr(entry, "_pending_permissions", {})
        permissions[item_id] = {
            "request_id": request.request_id,
            "options": request.options,
            "raw_params": request.raw_params,
        }
        # Also surface to the manager-level aggregation (mirrors Codex).
        self._pending_approvals[item_id] = {
            "task_id": task_id,
            "session_id": workspace_id,
            "method": "session/request_permission",
            "params": request.raw_params,
            "item_id": item_id,
            "request_id": request.request_id,
            "options": request.options,
            "execution_process_id": execution_process_id,
        }
        if self._event_bus:
            await self._event_bus.append(
                {
                    "type": "approval_required",
                    "item_id": item_id,
                    "method": "session/request_permission",
                    "params": request.raw_params,
                    "options": request.options,
                    "task_id": task_id,
                    "session_id": workspace_id,
                    "execution_process_id": execution_process_id,
                }
            )
        # Fail-closed timeout: resolve as cancelled if no human decision arrives.
        permission_timeout = await self._permission_timeout_s(task)
        timeout_tasks: set[asyncio.Task[None]] = getattr(entry, "_permission_timeout_tasks", set())
        timeout_task = asyncio.create_task(
            self._permission_timeout(item_id, entry, request, permission_timeout),
            name=f"acp-permission-timeout-{item_id}",
        )
        timeout_tasks.add(timeout_task)
        timeout_task.add_done_callback(timeout_tasks.discard)
        entry._permission_timeout_tasks = timeout_tasks  # type: ignore[attr-defined]

    async def _permission_timeout_s(self, task: CodexTask | None) -> float:
        # Read from the ACP executor config when resolvable; fall back to the
        # base env default. Kept defensive because the config may have been
        # edited mid-turn. Uses the async loader because this runs from inside
        # the event loop (the sync loader spins a fresh loop and deadlocks).
        executor_id = getattr(task, "executor", None) if task is not None else None
        if executor_id:
            try:
                config, _ = await self._load_acp_config(executor_id)
                if config is not None:
                    return float(config.permission_timeout_s)
            except Exception:
                pass
        return 300.0

    async def _permission_timeout(
        self,
        item_id: str,
        entry: AsyncProcessEntry,
        request: AcpPermissionRequest,
        timeout_s: float,
    ) -> None:
        try:
            await asyncio.sleep(timeout_s)
        except asyncio.CancelledError:
            return
        permissions: dict[str, dict[str, object]] = getattr(entry, "_pending_permissions", {})
        if item_id not in permissions:
            return
        logger.warning(
            "ACP permission %s timed out after %ss — resolving as cancelled",
            item_id,
            timeout_s,
        )
        client: AcpClient | None = getattr(entry, "_acp_client", None)
        if client is not None:
            with suppress(Exception):
                await client.resolve_permission(request.request_id, "cancelled")
        permissions.pop(item_id, None)
        self._pending_approvals.pop(item_id, None)
        if self._event_bus is not None:
            with suppress(Exception):
                await self._event_bus.append(
                    {
                        "type": "approval_resolved",
                        "item_id": item_id,
                        "decision": "cancelled",
                        "reason": "timeout",
                    }
                )

    def _make_closed_callback(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
    ) -> AcpClosedCallback:
        async def callback() -> None:
            # Peer closed mid-turn: surface failure if the turn never produced
            # a terminal result. The handshake/turn driver also wakes waiters
            # via its finally block; this is the safety net for an unexpected
            # EOF while we're still awaiting session/prompt.
            if not entry.had_error and entry.resume_session_id is None:
                entry.had_error = True
                if not entry.result_text:
                    entry.result_text = "ACP agent closed the connection before the turn completed."
            await self._append_log(
                workspace_id,
                "runtime",
                "ACP peer closed",
                task_id,
            )

        return callback

    # --- approval resolution (manager aggregation) --------------------

    async def resolve_approval(self, item_id: str, decision: str) -> bool:
        pending = self._pending_approvals.get(item_id)
        if pending is None:
            return False
        task_id = pending.get("task_id")
        workspace_id = pending.get("session_id")
        entry_key = task_id if isinstance(task_id, str) and task_id else workspace_id
        entry = self._processes.get(entry_key) if isinstance(entry_key, str) else None
        client: AcpClient | None = None
        if entry is not None:
            client = getattr(entry, "_acp_client", None)
        if client is None and isinstance(task_id, str):
            client = self._acp_clients.get(task_id)
        if client is None:
            return False

        outcome = self._map_decision_to_outcome(decision)
        request_id = pending.get("request_id")
        if request_id is None:
            return False
        success = await client.resolve_permission(request_id, outcome)
        if success:
            self._pending_approvals.pop(item_id, None)
            if entry is not None:
                permissions: dict[str, dict[str, object]] = getattr(
                    entry, "_pending_permissions", {}
                )
                permissions.pop(item_id, None)
            if self._event_bus is not None:
                await self._event_bus.append(
                    {
                        "type": "approval_resolved",
                        "item_id": item_id,
                        "task_id": task_id,
                        "session_id": workspace_id,
                        "decision": decision,
                        "outcome": outcome,
                        "execution_process_id": pending.get("execution_process_id"),
                    }
                )
        return success

    @staticmethod
    def _map_decision_to_outcome(decision: str) -> str:
        """Map the console's generic approval decisions onto ACP outcomes."""
        normalized = (decision or "").strip().lower()
        if normalized in ("accept", "approve"):
            return "allow_once"
        if normalized in ("acceptforsession", "accept_for_session", "allow_always"):
            return "allow_always"
        if normalized in ("decline", "reject"):
            return "reject_once"
        if normalized in ("decline_always", "reject_always"):
            return "reject_always"
        if normalized in ("cancel", "cancelled"):
            return "cancelled"
        # Unknown decision: fail closed.
        return "reject_once"

    def get_pending_approvals(self) -> dict[str, dict[str, object]]:
        return self._pending_approvals.copy()

    # --- termination ---------------------------------------------------

    async def terminate_task(self, task_id: str) -> None:
        # Best-effort: tell the agent to cancel the current turn and resolve
        # every outstanding permission as cancelled before tearing down.
        client = self._acp_clients.pop(task_id, None)
        if client is not None:
            with suppress(Exception):
                await client.cancel()
            # Resolve any still-pending permissions for this task as cancelled.
            for item_id, pending in list(self._pending_approvals.items()):
                if pending.get("task_id") != task_id:
                    continue
                request_id = pending.get("request_id")
                if request_id is not None:
                    with suppress(Exception):
                        await client.resolve_permission(request_id, "cancelled")
                self._pending_approvals.pop(item_id, None)
                if self._event_bus is not None:
                    with suppress(Exception):
                        await self._event_bus.append(
                            {
                                "type": "approval_resolved",
                                "item_id": item_id,
                                "task_id": task_id,
                                "session_id": pending.get("session_id"),
                                "decision": "cancelled",
                                "outcome": "cancelled",
                                "reason": "task_cancelled",
                                "execution_process_id": pending.get("execution_process_id"),
                            }
                        )
        # Delegate to base for process cleanup + DB terminalization.
        await super().terminate_task(task_id)


# Local import alias to avoid pulling the statuses module at module load when
# the runtime is only being constructed (it imports lazily where needed).
def _is_terminal(status: str) -> bool:
    from app.application.task_statuses import is_task_terminal_status

    return is_task_terminal_status(status)
