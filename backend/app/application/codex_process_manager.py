"""
Facade for backend execution runtimes.

Codex uses app-server / JSON-RPC. Claude uses a persistent stdin stream-json
session model. This facade routes each executor to its own async runtime.

Phase 3: Async-only runtime - no more sync threading.Thread paths.
"""

from __future__ import annotations  # noqa: I001


from typing import Any

from app.application.claude_process_runtime import ClaudeProcessRuntime
from app.application.codex_app_server_runtime import CodexAppServerRuntime
from app.application.process_runtime_common import AsyncProcessEntry  # noqa: F401


class CodexProcessManager:
    def __init__(
        self, codex_store, log_store, data_dir=None, event_bus=None, refresh_task_result=None
    ):
        shared_processes = {}
        # Secondary index keyed by task_id for fast lookup when multiple tasks
        # share the same workspace_id (Phase 4: concurrent same-role instances).
        # Runtimes already key _processes by `task_id or workspace_id`, so this
        # dict is a convenience alias that makes terminate_task O(1) without
        # iterating the full shared_processes dict.
        self._task_processes: dict[str, Any] = {}
        self._processes = shared_processes
        self._codex_runtime = CodexAppServerRuntime(
            codex_store=codex_store,
            log_store=log_store,
            data_dir=data_dir,
            event_bus=event_bus,
            processes=shared_processes,
            refresh_task_result=refresh_task_result,
        )
        self._claude_runtime = ClaudeProcessRuntime(
            codex_store=codex_store,
            log_store=log_store,
            data_dir=data_dir,
            event_bus=event_bus,
            processes=shared_processes,
            refresh_task_result=refresh_task_result,
        )
        self._codex_store = codex_store
        self._log_store = log_store
        self._data_dir = data_dir or "/tmp"
        self._event_bus = event_bus
        self._refresh_task_result = refresh_task_result

    @property
    def codex_store(self):
        return self._codex_store

    @codex_store.setter
    def codex_store(self, value):
        self._codex_store = value
        self._codex_runtime.codex_store = value
        self._claude_runtime.codex_store = value

    @property
    def log_store(self):
        return self._log_store

    @log_store.setter
    def log_store(self, value):
        self._log_store = value
        self._codex_runtime.log_store = value
        self._claude_runtime.log_store = value

    @property
    def refresh_task_result(self):
        return self._refresh_task_result

    @refresh_task_result.setter
    def refresh_task_result(self, value):
        self._refresh_task_result = value
        self._codex_runtime.refresh_task_result = value
        self._claude_runtime.refresh_task_result = value

    def check_availability(self) -> bool:
        return self._codex_runtime.check_availability()

    async def launch(self, workspace_id: str | None = None, **legacy_kwargs):
        return await self._codex_runtime.launch(workspace_id=workspace_id, **legacy_kwargs)

    async def write_input_async(
        self,
        session_id: str | None = None,
        input_text: str = "",
        wait: bool = True,
        task_id: str | None = None,
        executor: str = "codex",
        provider: str | None = None,
        model: str | None = None,
        resume_session_id: str | None = None,
        resume_message_id: str | None = None,
        cwd: str | None = None,
        workspace_id: str | None = None,
        env_overrides: dict[str, str] | None = None,
        force_new_session: bool = False,
        **legacy_kwargs,
    ) -> str:
        """Async write_input - awaits runtime's write_input_async directly."""
        resolved_workspace_id = workspace_id or session_id or legacy_kwargs.get("workspace_id")
        runtime = self._codex_runtime if executor == "codex" else self._claude_runtime

        result = await runtime.write_input_async(
            workspace_id=resolved_workspace_id,
            input_text=input_text,
            wait=wait,
            task_id=task_id,
            executor=executor,
            provider=provider,
            model=model,
            resume_session_id=resume_session_id,
            resume_message_id=resume_message_id,
            cwd=cwd,
            env_overrides=env_overrides,
            force_new_session=force_new_session,
            **legacy_kwargs,
        )
        # Mirror the entry into the secondary task_id index so concurrent
        # same-role tasks (Phase 4) can be terminated individually without
        # iterating the full shared _processes dict.
        if task_id and task_id in self._processes:
            self._task_processes[task_id] = self._processes[task_id]
        return result

    async def terminate(self, workspace_id: str | None = None, **legacy_kwargs):
        for runtime in (self._codex_runtime, self._claude_runtime):
            try:  # noqa: SIM105
                await runtime.terminate(workspace_id=workspace_id, **legacy_kwargs)
            except KeyError:
                pass
        resolved_workspace_id = workspace_id or legacy_kwargs.get("session_id")
        workspace = await self._codex_store.load_codex_workspace(resolved_workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {resolved_workspace_id} not found")
        return workspace

    async def terminate_all(self):
        terminated = []
        for runtime in (self._codex_runtime, self._claude_runtime):
            terminated.extend(await runtime.terminate_all())
        return terminated

    async def terminate_task(self, task_id: str):
        # Clean up the secondary task_id index entry if present.
        self._task_processes.pop(task_id, None)
        for runtime in (self._codex_runtime, self._claude_runtime):
            await runtime.terminate_task(task_id)

    async def resolve_approval(self, item_id: str, decision: str) -> bool:
        return await self._codex_runtime.resolve_approval(item_id, decision)

    def get_pending_approvals(self) -> dict[str, dict]:
        return self._codex_runtime.get_pending_approvals()

    def _make_app_server_notification_callback(self, workspace_id: str, task_id: str | None):
        return self._codex_runtime._make_app_server_notification_callback(workspace_id, task_id)
