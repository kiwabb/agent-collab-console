"""
Facade for backend execution runtimes.

Codex uses app-server / JSON-RPC. Claude uses a persistent stdin stream-json
session model. This facade routes each executor to its own async runtime.

Phase 3: Async-only runtime - no more sync threading.Thread paths.
"""

from __future__ import annotations  # noqa: I001


from collections.abc import Awaitable, Callable
from typing import cast

from app.application import timeouts
from app.application.acp_process_runtime import AcpProcessRuntime, CatalogLoader
from app.application.claude_process_runtime import ClaudeProcessRuntime
from app.application.codex_app_server_runtime import CodexAppServerRuntime
from app.application.json_rpc_client import JsonObject
from app.application.process_runtime_common import (
    AsyncProcessEntry,
    RefreshTaskResult,
    RuntimeCodexStore,
    RuntimeEventBus,
    RuntimeLogStore,
)
from app.application.runtime_catalog_service import RuntimeCatalogStore
from app.domain.models import CodexSession, RuntimeCatalog


class CodexProcessManager:
    def __init__(
        self,
        codex_store: RuntimeCodexStore,
        log_store: RuntimeLogStore,
        data_dir: str | None = None,
        event_bus: RuntimeEventBus | None = None,
        refresh_task_result: RefreshTaskResult | None = None,
        catalog_loader: CatalogLoader | None = None,
    ) -> None:
        shared_processes: dict[str, AsyncProcessEntry] = {}
        # Secondary index keyed by task_id for fast lookup when multiple tasks
        # share the same workspace_id (Phase 4: concurrent same-role instances).
        # Runtimes already key _processes by `task_id or workspace_id`, so this
        # dict is a convenience alias that makes terminate_task O(1) without
        # iterating the full shared_processes dict.
        self._task_processes: dict[str, AsyncProcessEntry] = {}
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
        # ACP runtime: catalog_loader resolves the live AcpRuntimeConfig per
        # turn from the runtime catalog. Default loader routes through
        # RuntimeCatalogService against this manager's current codex_store so
        # store swaps (setter below) are honoured. Use a bound method so the
        # loader always reads the live ``self._codex_store``.
        self._catalog_loader = catalog_loader or self._default_catalog_loader
        self._acp_runtime = AcpProcessRuntime(
            codex_store=codex_store,
            log_store=log_store,
            catalog_loader=self._catalog_loader,
            data_dir=data_dir,
            event_bus=event_bus,
            processes=shared_processes,
            refresh_task_result=refresh_task_result,
        )
        self._codex_store = codex_store
        self._log_store = log_store
        self._data_dir = data_dir or timeouts.DEFAULT_CODEX_DATA_DIR
        self._event_bus = event_bus
        self._refresh_task_result = refresh_task_result

    async def _default_catalog_loader(self) -> RuntimeCatalog:
        """Default catalog loader: ``RuntimeCatalogService`` over the live store.

        The injected store doubles as a :class:`RuntimeCatalogStore` (it owns
        ``load_runtime_catalog``/``save_runtime_catalog``); the service surfaces
        the non-optional ``RuntimeCatalog`` (with default-creation semantics)
        that :meth:`AcpProcessRuntime._load_acp_config` expects. Reads
        ``self._codex_store`` on every call so the setter swap is honoured.
        """
        from app.application.runtime_catalog_service import RuntimeCatalogService

        # ``RuntimeCodexStore`` (the manager's store protocol) does not declare
        # the catalog load/save methods, but the concrete store passed in at
        # bootstrap (``AsyncSQLiteStore``) satisfies both protocols. Cast at the
        # boundary so mypy sees the ``RuntimeCatalogStore`` contract the service
        # requires, matching the pattern used in ``conductor_main_loop``.
        return await RuntimeCatalogService(
            cast(RuntimeCatalogStore, self._codex_store)
        ).load_catalog()

    @property
    def acp_runtime(self) -> AcpProcessRuntime:
        """Expose the ACP runtime for callers that need direct access."""
        return self._acp_runtime

    @property
    def codex_store(self) -> RuntimeCodexStore:
        return self._codex_store

    @codex_store.setter
    def codex_store(self, value: RuntimeCodexStore) -> None:
        self._codex_store = value
        self._codex_runtime.codex_store = value
        self._claude_runtime.codex_store = value
        self._acp_runtime.codex_store = value

    @property
    def log_store(self) -> RuntimeLogStore:
        return self._log_store

    @log_store.setter
    def log_store(self, value: RuntimeLogStore) -> None:
        self._log_store = value
        self._codex_runtime.log_store = value
        self._claude_runtime.log_store = value
        self._acp_runtime.log_store = value

    @property
    def refresh_task_result(self) -> RefreshTaskResult | None:
        return self._refresh_task_result

    @refresh_task_result.setter
    def refresh_task_result(self, value: RefreshTaskResult | None) -> None:
        self._refresh_task_result = value
        self._codex_runtime.refresh_task_result = value
        self._claude_runtime.refresh_task_result = value
        self._acp_runtime.refresh_task_result = value

    def check_availability(self) -> bool:
        return bool(self._codex_runtime.check_availability())

    def check_executor_availability(self, executor: str) -> bool:
        if executor == "codex":
            return bool(self._codex_runtime.check_availability())
        if executor == "claude":
            return bool(self._claude_runtime.check_availability())
        if executor == "acp":
            return bool(self._acp_runtime.check_availability())
        raise ValueError(f"unknown executor availability probe: {executor}")

    async def launch(
        self,
        workspace_id: str | None = None,
        **legacy_kwargs: object,
    ) -> CodexSession:
        workspace = await self._codex_runtime.launch(workspace_id=workspace_id, **legacy_kwargs)
        if not isinstance(workspace, CodexSession):
            raise TypeError("Codex runtime launch returned an unexpected workspace payload")
        return workspace

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
        command_args: list[str] | None = None,
        force_new_session: bool = False,
        **legacy_kwargs: object,
    ) -> str:
        """Async write_input - awaits runtime's write_input_async directly."""
        legacy_workspace_id = legacy_kwargs.get("workspace_id")
        resolved_workspace_id = (
            workspace_id
            or session_id
            or (legacy_workspace_id if isinstance(legacy_workspace_id, str) else None)
        )
        if executor == "codex":
            runtime: CodexAppServerRuntime | ClaudeProcessRuntime | AcpProcessRuntime = (
                self._codex_runtime
            )
        elif executor == "acp":
            runtime = self._acp_runtime
        elif executor == "claude":
            runtime = self._claude_runtime
        else:
            raise ValueError(f"unknown executor: {executor}")

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
            command_args=command_args,
            force_new_session=force_new_session,
            **legacy_kwargs,
        )
        # Mirror the entry into the secondary task_id index so concurrent
        # same-role tasks (Phase 4) can be terminated individually without
        # iterating the full shared _processes dict.
        if task_id and task_id in self._processes:
            self._task_processes[task_id] = self._processes[task_id]
        return result if isinstance(result, str) else str(result or "")

    async def terminate(
        self,
        workspace_id: str | None = None,
        **legacy_kwargs: object,
    ) -> CodexSession:
        for runtime in (self._codex_runtime, self._claude_runtime, self._acp_runtime):
            try:  # noqa: SIM105
                await runtime.terminate(workspace_id=workspace_id, **legacy_kwargs)
            except KeyError:
                pass
        legacy_session_id = legacy_kwargs.get("session_id")
        resolved_workspace_id = (
            workspace_id if workspace_id is not None else legacy_session_id
        )
        if not isinstance(resolved_workspace_id, str):
            raise KeyError(f"Workspace {resolved_workspace_id} not found")
        workspace = await self._codex_store.load_codex_workspace(resolved_workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {resolved_workspace_id} not found")
        return workspace

    async def terminate_all(self) -> list[str]:
        terminated = []
        for runtime in (self._codex_runtime, self._claude_runtime, self._acp_runtime):
            terminated.extend(await runtime.terminate_all())
        return terminated

    async def terminate_task(self, task_id: str) -> None:
        # Clean up the secondary task_id index entry if present.
        self._task_processes.pop(task_id, None)
        for runtime in (self._codex_runtime, self._claude_runtime, self._acp_runtime):
            await runtime.terminate_task(task_id)

    async def resolve_approval(self, item_id: str, decision: str) -> bool:
        # Route by item_id namespace: ACP item_ids are permission request ids
        # surfaced through the ACP runtime's _pending_approvals; codex item_ids
        # live in the codex runtime. Try codex first (it owns the bulk of
        # approvals), then ACP. A truthy result short-circuits.
        if await self._codex_runtime.resolve_approval(item_id, decision):
            return True
        return bool(await self._acp_runtime.resolve_approval(item_id, decision))

    def get_pending_approvals(self) -> dict[str, dict[str, object]]:
        # Merge both runtimes' pending approvals. ACP and codex use disjoint
        # item_id namespaces (codex uses its app-server item ids, ACP uses
        # permission request ids), so a plain dict merge cannot collide.
        merged: dict[str, dict[str, object]] = {}
        for source in (self._codex_runtime, self._acp_runtime):
            approvals = source.get_pending_approvals()
            for item_id, payload in approvals.items():
                if isinstance(payload, dict):
                    merged[str(item_id)] = {
                        str(key): value for key, value in payload.items()
                    }
        return merged

    def _make_app_server_notification_callback(
        self, workspace_id: str, task_id: str | None
    ) -> Callable[[str, JsonObject], Awaitable[bool]]:
        return self._codex_runtime._make_app_server_notification_callback(workspace_id, task_id)
