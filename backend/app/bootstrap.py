from __future__ import annotations  # noqa: I001

import os  # noqa: I001, RUF100
import logging
import shlex
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from app.application.session_service import SessionService
from app.application.orchestration_service import OrchestrationService
from app.application.approval_service import ApprovalService
from app.application.event_bus import event_bus
from app.adapters.fake_claude_adapter import FakeClaudeAdapter
from app.adapters.fake_codex_adapter import FakeCodexAdapter
from app.adapters.claude_cli_adapter import ClaudeCliAdapter
from app.adapters.codex_cli_adapter import CodexCliAdapter
from app.adapters.sqlite_store import SQLiteStore
from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.external_prototype_agent_store import AsyncExternalPrototypeAgentStore
from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import (
    PrototypeRendererWorker,
    PrototypeRendererWorkerError,
)
from app.adapters.prototype_runtime_worker import (
    PrototypeRuntimeWorker,
    PrototypeRuntimeWorkerError,
)
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.codex_task_runner import CodexTaskRunner
from app.application.help_orchestrator import HelpOrchestrator, HelpTaskRunner
from app.application.role_workflow_service import RoleWorkflowService, RoleWorkflowStore
from app.application.git_service import GitService
from app.application.project_service import ProjectService
from app.application.mcp_registry import McpRegistry
from app.application.project_startup_mcp import (
    PROJECT_STARTUP_MCP_DESCRIPTOR,
    ProjectStartupMcpService,
)
from app.application.project_startup_service import ProjectStartupConfigService
from app.application.prototype_ui_engineer_runner import PrototypeUiEngineerRunner
from app.application.structured_prototype_service import StructuredPrototypeService
from app.application.structured_prototype_ai_mcp import (
    PROTOTYPE_AI_MCP_DESCRIPTOR,
    PrototypeAiMcpService,
)
from app.application.structured_prototype_ai_runtime import PrototypeUiEngineerRuntime
from app.application.structured_prototype_ai_service import StructuredPrototypeAiService
from app.application.structured_prototype_generation_mcp import (
    GENERATION_MCP_DESCRIPTOR,
    StructuredPrototypeGenerationMcpService,
)
from app.application.structured_prototype_generation_runtime import (
    StructuredPrototypeGenerationRuntime,
)
from app.application.structured_prototype_generation_service import (
    StructuredPrototypeGenerationService,
)
from app.application.runtime_catalog_service import RuntimeCatalogService
from app.application.skill_service import SkillService
from app.application import timeouts
from app.application.worktree_manager import WorktreeManager
from app.application.external_prototype_agent_service import (
    ExternalPrototypeAgentService,
    UnavailableStructuredPrototypeCollaborationPort,
)
from app.application.structured_prototype_external_collaboration import (
    StructuredPrototypeExternalCollaboration,
)
from app.domain.models import CodexSession, CodexTask, LogEvent

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.application.codex_process_manager import CodexProcessManager


RefreshTaskResult = Callable[[CodexTask], Awaitable[object]]
AppendLogEventAsync = Callable[[LogEvent], Awaitable[None]]


class MockCodexStore(Protocol):
    async def load_codex_session(self, session_id: str) -> CodexSession | None: ...

    async def save_codex_session(self, session: CodexSession) -> None: ...

    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...

    async def save_codex_task(self, task: CodexTask) -> None: ...


class MockLogStore(Protocol):
    async def append_log_event(self, event: LogEvent) -> None: ...


class MockEventBus(Protocol):
    async def queue_log_event(self, event: LogEvent) -> None: ...

    async def append(self, event: dict[str, object]) -> None: ...


class RealProcessManagerFactory(Protocol):
    def __call__(
        self,
        *,
        codex_store: object,
        log_store: object,
        data_dir: str,
        event_bus: object,
    ) -> CodexProcessManager: ...


class MockProcessManagerFactory(Protocol):
    def __call__(
        self,
        *,
        codex_store: object,
        log_store: object,
        data_dir: str | None = None,
        event_bus: object | None = None,
    ) -> MockCodexProcessManager: ...


class TaskRunnerFactory(Protocol):
    def __call__(
        self,
        *,
        codex_store: object,
        event_bus: object,
        process_manager_factory: Callable[[], object],
        mock_manager_cls: type[MockCodexProcessManager],
        refresh_task_result: RefreshTaskResult,
        help_orchestrator_factory: object | None,
        role_workflow_service: RoleWorkflowService,
    ) -> CodexTaskRunner: ...


# Workflow DAG feature flag. Default ON now that PR5 migrations and PR6
# replanner are in place. Set WORKFLOW_DAG_ENABLED=false to temporarily roll
# back to the legacy phase pipeline (transition endpoints are deleted, so the
# rollback also requires reverting their removal).
WORKFLOW_DAG_ENABLED = timeouts.workflow_dag_enabled()


# Determine store path - default to backend/console.db
db_path_str = timeouts.sqlite_db_path()
# Make path relative to backend directory if not absolute
if not os.path.isabs(db_path_str):
    db_path = Path(__file__).parent.parent / db_path_str
else:
    db_path = Path(db_path_str)

# Create store if SQLite persistence is enabled (default: true for persistence)
use_sqlite = timeouts.use_sqlite()
store = SQLiteStore(db_path) if use_sqlite else None
async_store = AsyncSQLiteStore(db_path) if use_sqlite else None
structured_prototype_data_root_str = timeouts.structured_prototype_data_root()
if not os.path.isabs(structured_prototype_data_root_str):
    structured_prototype_data_root = (
        Path(__file__).parent.parent / structured_prototype_data_root_str
    )
else:
    structured_prototype_data_root = Path(structured_prototype_data_root_str)
structured_prototype_store = AsyncStructuredPrototypeStore(db_path) if use_sqlite else None
structured_prototype_object_store = (
    PrototypeObjectStore(structured_prototype_data_root) if use_sqlite else None
)
structured_prototype_artifact_store = (
    PrototypeRenderArtifactStore(structured_prototype_data_root) if use_sqlite else None
)
try:
    structured_prototype_runtime_worker = PrototypeRuntimeWorker() if use_sqlite else None
except PrototypeRuntimeWorkerError as exc:
    logger.warning(
        "prototype runtime worker unavailable: code=%s",
        exc.code,
    )
    structured_prototype_runtime_worker = None
try:
    structured_prototype_renderer_worker = PrototypeRendererWorker() if use_sqlite else None
except PrototypeRendererWorkerError as exc:
    logger.warning(
        "prototype renderer worker unavailable: code=%s",
        exc.code,
    )
    structured_prototype_renderer_worker = None
structured_prototype_service = (
    StructuredPrototypeService(
        store=structured_prototype_store,
        object_store=structured_prototype_object_store,
        runtime_worker=structured_prototype_runtime_worker,
        renderer_worker=structured_prototype_renderer_worker,
        artifact_store=structured_prototype_artifact_store,
    )
    if structured_prototype_store is not None and structured_prototype_object_store is not None
    else None
)
external_prototype_agent_store = (
    AsyncExternalPrototypeAgentStore(db_path) if use_sqlite else None
)
external_prototype_agent_service = (
    ExternalPrototypeAgentService(
        store=external_prototype_agent_store,
        collaboration=UnavailableStructuredPrototypeCollaborationPort(),
    )
    if external_prototype_agent_store is not None
    else None
)

# Initialize event bus with store for DB writes
# Phase 1: Use async store for EventBus when running in full async mode (CODEX_LAUNCH_ENABLED=true)
# For test/mock mode, use sync store to avoid async/sync mismatch
use_async_event_bus = timeouts.codex_launch_enabled() and use_sqlite
if use_async_event_bus and async_store is not None:
    event_bus.set_log_store(async_store)
elif async_store is not None:
    # Always use async_store if available to ensure consistency
    event_bus.set_log_store(async_store)
elif store is not None:
    event_bus.set_log_store(store)

# Use async_store for all services if available
effective_store = async_store if async_store is not None else store

# Wire the unified audit logger to the effective store (PR1). The background
# drain worker starts once both the store and the running loop are set; the loop
# is set in main.py's lifespan startup, mirroring event_bus.set_loop.
from app.application.audit_logger import audit_logger  # noqa: E402, I001, RUF100

if async_store is not None:
    audit_logger.set_store(async_store)
session_service = SessionService(store=effective_store)

# Configure adapter: REAL_CLI=true makes the system actually invoke a CLI to
# write code instead of returning mock strings. Default ON — without it the
# Engineer phase never patches the worktree and the system is just a doc
# generator. Set REAL_CLI=false for offline tests / demos.
use_real_cli = timeouts.real_cli_enabled()

worker_adapter: ClaudeCliAdapter | FakeClaudeAdapter
master_adapter: CodexCliAdapter | FakeCodexAdapter
if use_real_cli:
    # Real CLI adapters - commands configurable via CLAUDE_CMD and CODEX_CMD env vars
    # Values are space-separated shell commands. Defaults try the system
    # `claude` / `codex` binaries — if those aren't installed the adapter
    # call will fail loudly, which is the correct signal to the user.
    claude_cmd_str = timeouts.claude_cli_cmd()
    codex_cmd_str = timeouts.codex_cli_cmd()
    worker_adapter = ClaudeCliAdapter(command=shlex.split(claude_cmd_str))
    master_adapter = CodexCliAdapter(command=shlex.split(codex_cmd_str))
else:
    # Fake adapters - returns mock results for demo/testing
    worker_adapter = FakeClaudeAdapter()
    master_adapter = FakeCodexAdapter()

orchestration_service = OrchestrationService(
    session_service=session_service,
    event_bus=event_bus,
    master_adapter=master_adapter,
    worker_adapter=worker_adapter,
)

approval_service = ApprovalService(session_service=session_service)

# Codex session store (shared SQLite store handles all session types)
codex_store = effective_store  # Use async_store if available

# Git project + worktree services.
git_service = GitService()
project_service = (
    ProjectService(store=async_store, git=git_service) if async_store is not None else None
)
skill_service = SkillService(store=async_store) if async_store is not None else None
worktree_manager = WorktreeManager(git=git_service)

# Runtime catalog service used by the conductor and Claude UI engineer runner.
runtime_catalog_service = (
    RuntimeCatalogService(store=async_store) if async_store is not None else None
)
project_startup_config_service = (
    ProjectStartupConfigService(async_store) if async_store is not None else None
)
project_startup_mcp_service = (
    ProjectStartupMcpService(project_startup_config_service)
    if project_startup_config_service is not None
    else None
)
prototype_ui_engineer_runner: PrototypeUiEngineerRunner | None = None
prototype_ui_engineer_task_runner: CodexTaskRunner | None = None
structured_prototype_ai_mcp_service: PrototypeAiMcpService | None = None
structured_prototype_ai_service: StructuredPrototypeAiService | None = None
structured_prototype_generation_mcp_service: StructuredPrototypeGenerationMcpService | None = None
structured_prototype_generation_service: StructuredPrototypeGenerationService | None = None

# Codex process manager - lazy imported to avoid pty dependency on import
codex_process_manager: CodexProcessManager | MockCodexProcessManager | None = None


def check_codex_available() -> bool:
    """
    Returns True if the 'codex' binary is found in PATH.
    Wrapped as a function so tests can monkey-patch it to remove
    ambient machine state dependency.
    """
    return shutil.which("codex") is not None


class MockCodexProcessManager:
    """
    A no-op process manager for testing - does not spawn real processes.
    In the per-turn model, write_input() just logs the input and immediately
    returns (simulating an instant "done" response).
    Used when CODEX_LAUNCH_ENABLED=false to isolate tests from real process spawning.
    """

    def __init__(
        self,
        codex_store: MockCodexStore,
        log_store: MockLogStore | None,
        data_dir: str | None = None,
        event_bus: MockEventBus | None = None,
    ) -> None:
        self.codex_store = codex_store
        self.log_store = log_store
        self._processes: dict[str, object] = {}
        self._data_dir = data_dir or timeouts.DEFAULT_CODEX_DATA_DIR
        self._event_bus = event_bus

    def check_availability(self) -> bool:
        return True  # Pretend available so availability checks pass

    def check_executor_availability(self, executor: str) -> bool:
        if executor not in {"codex", "claude"}:
            raise ValueError(f"unknown executor availability probe: {executor}")
        return True

    def _get_log_path(self, session_id: str) -> str:
        return os.path.join(self._data_dir, f"mock_session_{session_id}.log")

    async def launch(self, session_id: str) -> CodexSession:
        """Initialize session for per-turn model (no process spawned)."""
        session = await self.codex_store.load_codex_session(session_id)
        if session is None:
            raise KeyError(f"Codex session {session_id} not found")
        session.status = "idle"
        session.log_path = self._get_log_path(session_id)
        session.last_active_at = __import__("datetime").datetime.now()
        await self.codex_store.save_codex_session(session)
        return session

    async def write_input(
        self,
        session_id: str,
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
        **_extra: object,
    ) -> str:
        """In per-turn model: just log input and mark session done. No real process."""
        from app.application.process_runtime_common import is_workspace_console_task

        session = await self.codex_store.load_codex_session(session_id)
        if session is None:
            raise KeyError(f"Codex session {session_id} not found")
        session.status = "responding"
        session.last_active_at = __import__("datetime").datetime.now()
        mock_task = await self.codex_store.load_codex_task(task_id) if task_id else None
        is_console = mock_task is None or is_workspace_console_task(mock_task)
        if executor == "codex" and is_console:
            # Only the human console task touches the shared per-workspace pointer.
            session.thread_id = (
                resume_session_id or session.thread_id or f"mock-thread-{session_id}"
            )
        await self.codex_store.save_codex_session(session)
        await self._append_log(session_id, "stdin", input_text, task_id)
        if task_id:
            task = mock_task
            if task is not None:
                # Role tasks keep per-task identity: only carry the explicitly
                # passed resume id (or a fresh mock id), never the shared pointer.
                fallback = session.thread_id if is_console else None
                task.resume_session_id = (
                    resume_session_id or fallback or f"mock-thread-{session_id}"
                )
                task.resume_message_id = resume_message_id
                task.result = task.result or input_text.strip()
                task.status = "done"
                task.updated_at = __import__("datetime").datetime.now()
                await self.codex_store.save_codex_task(task)
        # Simulate instant done response
        session.status = "done"
        session.last_active_at = __import__("datetime").datetime.now()
        await self.codex_store.save_codex_session(session)
        return "done" if wait else "responding"

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
        env_overrides: dict[str, str] | None = None,
        command_args: list[str] | None = None,
        force_new_session: bool = False,
        **legacy_kwargs: object,
    ) -> str:
        """Async version of write_input - delegates to write_input for mock."""
        if session_id is None:
            raise ValueError("session_id is required")
        return await self.write_input(
            session_id,
            input_text,
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

    async def terminate(self, session_id: str) -> CodexSession:
        """Set session back to idle (stops any in-progress turn)."""
        self._processes.pop(session_id, None)
        session = await self.codex_store.load_codex_session(session_id)
        if session is None:
            raise KeyError(f"Codex session {session_id} not found")
        session.status = "idle"
        session.last_active_at = __import__("datetime").datetime.now()
        await self.codex_store.save_codex_session(session)
        return session

    async def terminate_all(self) -> list[str]:
        """Mark all sessions as idle and clear _processes."""
        terminated = []
        for session_id in list(self._processes.keys()):
            try:
                await self.terminate(session_id)
                terminated.append(session_id)
            except Exception:
                logger.debug(
                    "mock process termination failed: session_id=%s", session_id, exc_info=True
                )
        return terminated

    async def terminate_task(self, task_id: str) -> None:
        self._processes.pop(task_id, None)

    async def resolve_approval(self, item_id: str, decision: str) -> bool:
        return False

    def get_pending_approvals(self) -> dict[str, dict[str, object]]:
        return {}

    async def _append_log(
        self,
        session_id: str,
        stream: str,
        content: str,
        task_id: str | None = None,
    ) -> None:
        from app.domain.models import LogEvent  # noqa: I001
        from uuid import uuid4

        now = __import__("datetime").datetime.now()
        execution_process_id = None
        if task_id:
            load_task = getattr(self.codex_store, "load_codex_task", None)
            task = await load_task(task_id) if callable(load_task) else None
            execution_process_id = task.last_execution_process_id if task else None
        event = LogEvent(
            id=str(uuid4()),
            session_id=session_id,
            stream=stream,
            content=content,
            task_id=task_id,
            execution_process_id=execution_process_id,
            created_at=now,
        )
        if self._event_bus is not None:
            await self._event_bus.queue_log_event(event)
        # In mock mode, also persist directly to ensure test stability
        if self.log_store is not None:
            append_log_event_async = getattr(self.log_store, "append_log_event_async", None)
            if callable(append_log_event_async):
                await cast(AppendLogEventAsync, append_log_event_async)(event)
            else:
                await self.log_store.append_log_event(event)
        self._publish_to_ws(session_id, event.id, stream, content, now.isoformat())
        if self._event_bus is not None:
            await self._event_bus.append(
                {
                    "type": "log",
                    "session_id": session_id,
                    "stream": stream,
                    "content": content,
                    "task_id": task_id,
                    "execution_process_id": execution_process_id,
                }
            )

    def _publish_to_ws(
        self,
        session_id: str,
        event_id: str,
        stream: str,
        content: str,
        created_at_iso: str,
    ) -> None:
        from app.interfaces.codex_ws import stream_manager

        stream_manager.buffer_pending(
            session_id,
            {
                "id": event_id,
                "stream": stream,
                "content": content,
                "created_at": created_at_iso,
            },
        )

    def buffer_pending(self, session_id: str, event: dict[str, object]) -> None:
        from app.interfaces.codex_ws import stream_manager

        stream_manager.buffer_pending(session_id, event)


def get_codex_process_manager() -> CodexProcessManager | MockCodexProcessManager:
    global codex_process_manager
    if codex_process_manager is None:
        if timeouts.codex_launch_enabled():
            from app.application.codex_process_manager import CodexProcessManager

            data_dir = timeouts.codex_data_dir()
            real_manager_factory = cast(RealProcessManagerFactory, CodexProcessManager)
            codex_process_manager = real_manager_factory(
                codex_store=codex_store,
                log_store=codex_store,
                data_dir=data_dir,
                event_bus=event_bus,
            )
        else:
            mock_manager_factory = cast(MockProcessManagerFactory, MockCodexProcessManager)
            codex_process_manager = mock_manager_factory(
                codex_store=codex_store, log_store=codex_store
            )
    return codex_process_manager


def check_claude_available() -> bool:
    return get_codex_process_manager().check_executor_availability("claude")


task_runner = None
help_orchestrator = None
role_workflow_service = RoleWorkflowService(
    codex_store=cast(RoleWorkflowStore | None, codex_store),
    project_startup_mcp_service=project_startup_mcp_service,
)


def get_task_runner(refresh_task_result: RefreshTaskResult) -> CodexTaskRunner:
    global task_runner
    if task_runner is None:
        task_runner_factory = cast(TaskRunnerFactory, CodexTaskRunner)
        task_runner = task_runner_factory(
            codex_store=codex_store,
            event_bus=event_bus,
            process_manager_factory=get_codex_process_manager,
            mock_manager_cls=MockCodexProcessManager,
            refresh_task_result=refresh_task_result,
            help_orchestrator_factory=None,
            role_workflow_service=role_workflow_service,
        )
        task_runner._help_orchestrator_factory = lambda: get_help_orchestrator(refresh_task_result)
    return task_runner


def get_help_orchestrator(refresh_task_result: RefreshTaskResult) -> HelpOrchestrator:
    global help_orchestrator
    if help_orchestrator is None:
        if async_store is None:
            raise RuntimeError("Help orchestration requires the async SQLite store")
        help_orchestrator = HelpOrchestrator(
            codex_store=async_store,
            event_bus=event_bus,
            task_runner=cast(HelpTaskRunner, get_task_runner(refresh_task_result)),
        )
    return help_orchestrator


async def _refresh_prototype_ui_engineer_task_result(_task: CodexTask) -> object:
    # Structured prototype MCP services persist the accepted typed result.
    return None


if async_store is not None:
    prototype_ui_engineer_task_runner_factory = cast(TaskRunnerFactory, CodexTaskRunner)
    prototype_ui_engineer_task_runner = prototype_ui_engineer_task_runner_factory(
        codex_store=async_store,
        event_bus=event_bus,
        process_manager_factory=get_codex_process_manager,
        mock_manager_cls=MockCodexProcessManager,
        refresh_task_result=_refresh_prototype_ui_engineer_task_result,
        help_orchestrator_factory=None,
        role_workflow_service=role_workflow_service,
    )
    prototype_ui_engineer_runner = PrototypeUiEngineerRunner(
        store=async_store,
        task_runner=prototype_ui_engineer_task_runner,
        worktree_manager=worktree_manager,
        claude_availability_probe=check_claude_available,
    )
    if (
        structured_prototype_store is not None
        and structured_prototype_object_store is not None
        and structured_prototype_service is not None
        and structured_prototype_renderer_worker is not None
        and structured_prototype_artifact_store is not None
    ):
        structured_prototype_ai_mcp_service = PrototypeAiMcpService()
        structured_prototype_ai_runtime = PrototypeUiEngineerRuntime(
            runner=prototype_ui_engineer_runner,
            mcp_service=structured_prototype_ai_mcp_service,
        )
        structured_prototype_ai_service = StructuredPrototypeAiService(
            store=structured_prototype_store,
            project_store=async_store,
            object_store=structured_prototype_object_store,
            structured_service=structured_prototype_service,
            runtime=structured_prototype_ai_runtime,
            renderer_worker=structured_prototype_renderer_worker,
            artifact_store=structured_prototype_artifact_store,
        )
        if structured_prototype_runtime_worker is not None:
            structured_prototype_generation_mcp_service = (
                StructuredPrototypeGenerationMcpService()
            )
            structured_prototype_generation_runtime = StructuredPrototypeGenerationRuntime(
                runner=prototype_ui_engineer_runner,
                mcp_service=structured_prototype_generation_mcp_service,
                object_store=structured_prototype_object_store,
            )
            structured_prototype_generation_service = StructuredPrototypeGenerationService(
                store=structured_prototype_store,
                project_store=async_store,
                object_store=structured_prototype_object_store,
                runtime=structured_prototype_generation_runtime,
                runtime_worker=structured_prototype_runtime_worker,
                renderer=structured_prototype_renderer_worker,
                artifact_store=structured_prototype_artifact_store,
            )

if (
    external_prototype_agent_store is not None
    and structured_prototype_store is not None
    and structured_prototype_service is not None
    and structured_prototype_ai_service is not None
):
    external_prototype_agent_service = ExternalPrototypeAgentService(
        store=external_prototype_agent_store,
        collaboration=StructuredPrototypeExternalCollaboration(
            store=structured_prototype_store,
            structured_service=structured_prototype_service,
            ai_service=structured_prototype_ai_service,
        ),
    )

mcp_registry = McpRegistry()
mcp_registry.register(PROJECT_STARTUP_MCP_DESCRIPTOR, project_startup_mcp_service)
mcp_registry.register(PROTOTYPE_AI_MCP_DESCRIPTOR, structured_prototype_ai_mcp_service)
mcp_registry.register(
    GENERATION_MCP_DESCRIPTOR,
    structured_prototype_generation_mcp_service,
)
