import os
import shlex
import shutil
from pathlib import Path

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
from app.application.codex_task_runner import CodexTaskRunner
from app.application.help_orchestrator import HelpOrchestrator
from app.application.role_workflow_service import RoleWorkflowService
from app.application.git_service import GitService
from app.application.project_service import ProjectService
from app.application.worktree_manager import WorktreeManager


# Determine store path - default to backend/console.db
db_path_str = os.getenv("SQLITE_DB_PATH", "console.db")
# Make path relative to backend directory if not absolute
if not os.path.isabs(db_path_str):
    db_path = Path(__file__).parent.parent / db_path_str
else:
    db_path = Path(db_path_str)

# Create store if SQLite persistence is enabled (default: true for persistence)
use_sqlite = os.getenv("USE_SQLITE", "true").lower() == "true"
store = SQLiteStore(db_path) if use_sqlite else None
async_store = AsyncSQLiteStore(db_path) if use_sqlite else None

# Initialize event bus with store for DB writes
# Phase 1: Use async store for EventBus when running in full async mode (CODEX_LAUNCH_ENABLED=true)
# For test/mock mode, use sync store to avoid async/sync mismatch
use_async_event_bus = os.getenv("CODEX_LAUNCH_ENABLED", "true").lower() != "false" and use_sqlite
if use_async_event_bus and async_store is not None:
    event_bus.set_log_store(async_store)
elif async_store is not None:
    # Always use async_store if available to ensure consistency
    event_bus.set_log_store(async_store)
elif store is not None:
    event_bus.set_log_store(store)

# Use async_store for all services if available
effective_store = async_store if async_store is not None else store
session_service = SessionService(store=effective_store)

# Configure adapter: use REAL_CLI=true for real subprocess execution
# Default is Fake*Adapter for safe/demo mode
use_real_cli = os.getenv("REAL_CLI", "false").lower() == "true"

if use_real_cli:
    # Real CLI adapters - commands configurable via CLAUDE_CMD and CODEX_CMD env vars
    # Values are space-separated shell commands, e.g. "python3 -c \"print('done')\""
    claude_cmd_str = os.getenv("CLAUDE_CMD", "python3 -c \"print('task completed')\"")
    codex_cmd_str = os.getenv("CODEX_CMD", "python3 -c \"print('planned')\"")
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
project_service = ProjectService(store=async_store, git=git_service) if async_store is not None else None
worktree_manager = WorktreeManager(git=git_service)

# Codex process manager - lazy imported to avoid pty dependency on import
codex_process_manager = None


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

    def __init__(self, codex_store, log_store, data_dir=None, event_bus=None):
        self.codex_store = codex_store
        self.log_store = log_store
        self._processes = {}
        self._data_dir = data_dir or "/tmp"
        self._event_bus = event_bus

    def check_availability(self) -> bool:
        return True  # Pretend available so availability checks pass

    def _get_log_path(self, session_id: str) -> str:
        return os.path.join(self._data_dir, f"mock_session_{session_id}.log")

    async def launch(self, session_id: str):
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
        env_overrides: dict | None = None,
        command_args: list | None = None,
        **_extra,
    ) -> str:
        """In per-turn model: just log input and mark session done. No real process."""
        session = await self.codex_store.load_codex_session(session_id)
        if session is None:
            raise KeyError(f"Codex session {session_id} not found")
        session.status = "responding"
        session.last_active_at = __import__("datetime").datetime.now()
        if executor == "codex":
            session.thread_id = resume_session_id or session.thread_id or f"mock-thread-{session_id}"
        await self.codex_store.save_codex_session(session)
        await self._append_log(session_id, "stdin", input_text, task_id)
        if task_id:
            task = await self.codex_store.load_codex_task(task_id)
            if task is not None:
                task.resume_session_id = resume_session_id or session.thread_id or f"mock-thread-{session_id}"
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
        **kwargs,
    ) -> str:
        """Async version of write_input - delegates to write_input for mock."""
        return await self.write_input(session_id, input_text, **kwargs)

    async def terminate(self, session_id: str):
        """Set session back to idle (stops any in-progress turn)."""
        self._processes.pop(session_id, None)
        session = await self.codex_store.load_codex_session(session_id)
        if session is None:
            raise KeyError(f"Codex session {session_id} not found")
        session.status = "idle"
        session.last_active_at = __import__("datetime").datetime.now()
        await self.codex_store.save_codex_session(session)
        return session

    async def terminate_all(self):
        """Mark all sessions as idle and clear _processes."""
        terminated = []
        for session_id in list(self._processes.keys()):
            try:
                await self.terminate(session_id)
                terminated.append(session_id)
            except Exception:
                pass
        return terminated

    async def _append_log(self, session_id, stream, content, task_id: str | None = None):
        from app.domain.models import LogEvent
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
            if hasattr(self.log_store, "append_log_event_async"):
                await self.log_store.append_log_event_async(event)
            else:
                await self.log_store.append_log_event(event)
            
        self._publish_to_ws(session_id, event.id, stream, content, now.isoformat())
        if self._event_bus is not None:
            await self._event_bus.append({
                "type": "log",
                "session_id": session_id,
                "stream": stream,
                "content": content,
                "task_id": task_id,
                "execution_process_id": execution_process_id,
            })

    def _publish_to_ws(self, session_id, event_id, stream, content, created_at_iso):
        from app.interfaces.codex_ws import stream_manager
        stream_manager.buffer_pending(session_id, {
            "id": event_id,
            "stream": stream,
            "content": content,
            "created_at": created_at_iso,
        })

    def buffer_pending(self, session_id, event):
        from app.interfaces.codex_ws import stream_manager
        stream_manager.buffer_pending(session_id, event)


def get_codex_process_manager():
    global codex_process_manager
    if codex_process_manager is None:
        if os.getenv("CODEX_LAUNCH_ENABLED", "true").lower() != "false":
            from app.application.codex_process_manager import CodexProcessManager
            data_dir = os.getenv("CODEX_DATA_DIR", "/tmp")
            codex_process_manager = CodexProcessManager(codex_store=codex_store, log_store=codex_store, data_dir=data_dir, event_bus=event_bus)
        else:
            codex_process_manager = MockCodexProcessManager(codex_store=codex_store, log_store=codex_store)
    return codex_process_manager


task_runner = None
help_orchestrator = None
role_workflow_service = RoleWorkflowService()


def get_task_runner(refresh_task_result):
    global task_runner
    if task_runner is None:
        task_runner = CodexTaskRunner(
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


def get_help_orchestrator(refresh_task_result):
    global help_orchestrator
    if help_orchestrator is None:
        help_orchestrator = HelpOrchestrator(
            codex_store=codex_store,
            event_bus=event_bus,
            task_runner=get_task_runner(refresh_task_result),
        )
    return help_orchestrator
