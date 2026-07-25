import asyncio
import inspect
import json
import logging
import os
import signal
import subprocess  # nosec B404
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.application import timeouts
from app.application.help_orchestrator import is_help_request_terminal_status
from app.application.task_statuses import (
    execution_process_state_for_task,
    is_task_active_status,
    is_task_failure_status,
    is_task_success_status,
    is_task_terminal_status,
)
from app.application.usage_utils import (
    extract_usage,
    price_tokens,
    read_usage_float,
    read_usage_int,
)
from app.domain.models import (
    AgentCallTrace,
    CodexSession,
    CodexTask,
    CodexTaskMessage,
    ExecutionProcess,
    HelpRequest,
    LogEvent,
)
from app.json_safety import object_dict, string_value

# Shared local CLI process runtime cleanup boundary.
logger = logging.getLogger(__name__)
RUNTIME_TRACE_PREVIEW_LIMIT = 4_000


JsonEvent = dict[str, object]
RefreshTaskResult = Callable[[CodexTask], Awaitable[object]]


class RuntimeCodexStore(Protocol):
    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None: ...

    async def save_codex_workspace(self, workspace: CodexSession) -> None: ...

    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...

    async def save_codex_task(self, task: CodexTask) -> None: ...

    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None: ...

    async def load_execution_process(self, process_id: str) -> ExecutionProcess | None: ...

    async def list_codex_task_messages(
        self, task_id: str, execution_process_id: str | None = None
    ) -> list[CodexTaskMessage]: ...

    async def update_execution_process_usage(
        self,
        process_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        total_cost_usd: float | None = None,
    ) -> None: ...

    async def save_codex_task_message(self, message: CodexTaskMessage) -> None: ...

    async def load_help_request(self, help_request_id: str) -> HelpRequest | None: ...


class RuntimeLogStore(Protocol):
    async def append_log_event(self, event: LogEvent) -> None: ...


class RuntimeEventBus(Protocol):
    async def append(self, event: JsonEvent) -> None: ...

    async def queue_log_event(self, event: LogEvent) -> None: ...


class RuntimeHelpOrchestrator(Protocol):
    async def request_help_from_runtime(
        self,
        *,
        task_id: str,
        workspace_id: str,
        target_executor: str,
        title: str,
        prompt: str,
        source_executor: str,
        context_summary: object | None = None,
    ) -> None: ...

    async def complete_help_request(
        self,
        help_request_id: str,
        *,
        child_status: str,
        child_result: str | None,
    ) -> None: ...


def is_agent_message_item_type(item_type: str | None) -> bool:
    normalized = str(item_type or "").strip().lower().replace("-", "_")
    return normalized in {"agent_message", "agentmessage"}


def _runtime_trace_json_and_preview(value: object) -> tuple[str, str, bool]:
    raw = json.dumps(value, ensure_ascii=False, default=str)
    preview = raw[:RUNTIME_TRACE_PREVIEW_LIMIT]
    return raw, preview, False


def is_cli_control_payload(text: str | None) -> bool:
    """True when text is a stray CLI/cmux control envelope (e.g. a SessionStart
    hook line) rather than real agent output. Such lines must never become a
    subagent's result/summary — when an agent fails before emitting any real
    text, the CLI can echo its hook envelope as the final `result` string."""
    if not text:
        return False
    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return False
    try:
        obj = json.loads(s)
    except (ValueError, TypeError):
        return False
    if not isinstance(obj, dict):
        return False
    if obj.get("type") == "system":
        return True
    return any(key in obj for key in ("hook_name", "hook_event", "hook_id"))


def is_codex_protocol_frame(text: str | None) -> bool:
    """True when text is a raw codex app-server JSON-RPC notification frame
    (e.g. {"method":"item/agentMessage/delta","params":{...}}) rather than the
    agent's actual answer. codex streams its reply as many such frames; when a
    turn is interrupted (e.g. a watchdog kill) one of them can be left behind as
    result_text. Such a frame must never be persisted as task.result — it makes
    the Conductor read the subagent as an empty/garbage failure."""
    if not text:
        return False
    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return False
    try:
        obj = json.loads(s)
    except (ValueError, TypeError):
        return False
    if not isinstance(obj, dict):
        return False
    method = obj.get("method")
    # codex methods are path-segmented (item/..., turn/..., thread/...). A real
    # role artifact JSON never carries a top-level "method" string.
    return isinstance(method, str) and ("params" in obj or "/" in method)


def is_unusable_result_text(text: str | None) -> bool:
    """A result string that must not be captured as a task result/summary:
    either a CLI control envelope or a raw codex protocol frame."""
    return is_cli_control_payload(text) or is_codex_protocol_frame(text)


class WorkspaceConsoleTaskLike(Protocol):
    @property
    def issue_id(self) -> str | None: ...

    @property
    def task_kind(self) -> str | None: ...

    @property
    def parent_task_id(self) -> str | None: ...


def is_workspace_console_task(task: WorkspaceConsoleTaskLike | None) -> bool:
    """True only for the human workspace-console chat task (send_workspace_input).

    That task legitimately shares the per-workspace CLI session pointer
    (`workspace.thread_id` / `workspace.claude_thread_id`) so a human's
    consecutive messages keep one conversation. Every Conductor-dispatched role
    task and every help child uses strict per-task session identity instead —
    they must never read or write the shared workspace pointer, otherwise one
    broken session poisons every role in the workspace."""
    if task is None:
        return False
    if getattr(task, "issue_id", None) is not None:
        return False
    if getattr(task, "task_kind", "normal") not in (None, "normal"):
        return False
    return getattr(task, "parent_task_id", None) is None


@dataclass
class ProcessEntry:
    proc: subprocess.Popen[bytes]
    output_thread: threading.Thread | None
    alive: bool
    session_id: str
    executor: str
    cwd: str
    resume_session_id: str | None
    resume_message_id: str | None = None
    pending_waiters: list[asyncio.Event] = field(default_factory=list)
    result_text: str | None = None
    had_error: bool = False
    help_requested: bool = False

    @property
    def workspace_id(self) -> str:
        return self.session_id


@dataclass(frozen=True)
class RuntimeTaskContext:
    execution_process_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    issue_id: str | None = None
    is_workspace_console: bool = False

@dataclass
class AsyncProcessEntry:
    """Async-compatible process entry for asyncio-based subprocess management."""

    proc: asyncio.subprocess.Process
    output_task: asyncio.Task[None] | None
    alive: bool
    session_id: str
    executor: str
    cwd: str
    resume_session_id: str | None
    task_id: str | None = None
    resume_message_id: str | None = None
    pending_waiters: list[asyncio.Event] = field(default_factory=list)
    result_text: str | None = None
    had_error: bool = False
    help_requested: bool = False
    # True once a genuine assistant/result turn (real text) was captured. A run
    # that emitted only CLI control lines (e.g. a SessionStart hook) never flips
    # this, so its captured session id is treated as dead and not carried into a
    # retry — preventing the "resume the empty session → fail → retry" loop.
    produced_real_turn: bool = False
    # Token-streaming state: text we last broadcasted to clients via message_delta.
    # On each new assistant partial, emit (new_text - last_emitted_assistant_text)
    # as a delta event. `delta_seq` is monotonically increasing per-entry.
    last_emitted_assistant_text: str = ""
    delta_seq: int = 0
    # Tool-event dedup: tool_use IDs already mirrored to the log store.
    # Claude stream-json can re-emit the same assistant message multiple times
    # while a turn is in-flight, so we guard the emission per tool_use_id.
    emitted_tool_use_ids: set[str] = field(default_factory=set)
    emitted_tool_result_ids: set[str] = field(default_factory=set)
    # Codex item tracking: maps item.id to a started_at timestamp so we can
    # compute durationMs on completion.
    tool_item_started_at: dict[str, datetime] = field(default_factory=dict)
    # Idle-timeout bookkeeping: monotonic timestamp of the most recent stdout
    # line / IPC event we received from the subprocess. The Codex runtime
    # watches this and aborts a task when nothing has streamed for too long
    # (default 180s) — the long total-turn timeout alone isn't enough to
    # catch a hung tool-result loop.
    last_event_at: float = 0.0
    idle_timed_out: bool = False
    idle_timeout_seconds: int | None = None
    max_timeout_seconds: int | None = None
    turn_watchdog_task: asyncio.Task[None] | None = None
    timeout_reason: str | None = None
    # Latest activity kind tracked by _capture_on_reader for heartbeat phase
    # reporting: "text" | "reasoning" | "tool" | "idle". Used by the AgentLive
    # WorkingIndicator on the frontend so users see "Reasoning…" / "Running
    # tool: X" / "Last activity Xs ago" instead of a blank spinner.
    last_activity_kind: str = "idle"
    # Throttle bookkeeping for worktree_dirty events. The frontend GitInfoCard /
    # DiffPanel subscribe to this to refetch the diff stat while engineer code
    # changes are in flight. Without throttling, a chatty engineer turn would
    # storm the event bus.
    last_worktree_dirty_at: float = 0.0
    cached_issue_id: str | None = None
    task_context: RuntimeTaskContext | None = None

    @property
    def workspace_id(self) -> str:
        return self.session_id


def _sanitize_chat_reply(text: str) -> str:
    """If a chat-mode agent reply is actually structured JSON (weak instruction
    following), replace it with a friendly hint instead of dumping the blob.

    Heuristic: trimmed reply starts with `{` or `[` and at least the first 50
    chars contain a JSON-looking shape.
    """
    if not text:
        return text
    stripped = text.strip()
    if not stripped:
        return text
    if stripped[0] not in ("{", "["):
        return text
    # Confidence check: try to parse the first ~10kB as JSON. If it succeeds,
    # this is definitely a JSON dump that doesn't belong in a chat thread.
    import json as _json

    sample = stripped[:10000]
    try:
        _json.loads(sample)
    except Exception:
        return text  # Probably starts with { but not actually JSON — keep as-is
    return (
        "(模型未按对话格式回复, 输出了结构化 JSON。已忽略原文以免覆盖产物。"
        "可重试或切换为更擅长对话的模型。)"
    )


class BaseProcessRuntime:
    codex_store: RuntimeCodexStore
    log_store: RuntimeLogStore
    _data_dir: str
    _event_bus: RuntimeEventBus | None
    _processes: dict[str, AsyncProcessEntry]
    help_orchestrator: RuntimeHelpOrchestrator | None
    refresh_task_result: RefreshTaskResult | None

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
        self.codex_store = codex_store
        self.log_store = log_store
        self._data_dir = data_dir or timeouts.DEFAULT_CODEX_DATA_DIR
        self._event_bus = event_bus
        self._processes = processes if processes is not None else {}
        self.help_orchestrator = help_orchestrator
        self.refresh_task_result = refresh_task_result

    def _resolve_workspace_id(
        self,
        workspace_id: str | None = None,
        **legacy_kwargs: object,
    ) -> str:
        resolved_workspace_id = workspace_id or legacy_kwargs.pop("session_id", None)
        if legacy_kwargs:
            unexpected = ", ".join(sorted(legacy_kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")
        if not isinstance(resolved_workspace_id, str) or not resolved_workspace_id:
            raise TypeError("workspace_id is required")
        return resolved_workspace_id

    async def launch(
        self,
        workspace_id: str | None = None,
        **legacy_kwargs: object,
    ) -> CodexSession:
        workspace_id = self._resolve_workspace_id(workspace_id, **legacy_kwargs)
        workspace = await self.codex_store.load_codex_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        log_path = self._get_log_path(workspace_id)
        workspace.log_path = log_path
        workspace.status = "idle"
        workspace.last_active_at = datetime.now()
        await self.codex_store.save_codex_workspace(workspace)
        return workspace

    async def terminate(
        self,
        workspace_id: str | None = None,
        **legacy_kwargs: object,
    ) -> CodexSession | None:
        workspace_id = self._resolve_workspace_id(workspace_id, **legacy_kwargs)
        killed_task_ids: list[str] = []
        for process_key, entry in list(self._processes.items()):
            if not self._owns_entry(entry):
                continue
            if process_key != workspace_id and entry.workspace_id != workspace_id:
                continue
            self._processes.pop(process_key, None)
            await self._cleanup_entry(process_key, entry)
            entry_task_id = getattr(entry, "task_id", None)
            if entry_task_id:
                killed_task_ids.append(entry_task_id)

        # Mark every task / EP we killed as failed in the DB and broadcast the
        # change. Without this the UI keeps rendering "Running" because the EP
        # status was never updated when we yanked the process out.
        for task_id in killed_task_ids:
            try:
                task = await self.codex_store.load_codex_task(task_id)
            except Exception:
                task = None
            if task is None or is_task_terminal_status(task.status):
                continue
            task.status = "failed"
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)
            execution_process_id = getattr(task, "last_execution_process_id", None)
            if execution_process_id:
                with suppress(Exception):
                    await self.codex_store.update_execution_process_status(
                        execution_process_id,
                        "Killed",
                        exit_code=None,
                        completed_at=datetime.now(),
                    )
            if self._event_bus is not None:
                with suppress(Exception):
                    await self._emit_task_status(
                        task,
                        "failed",
                        result=task.result,
                        execution_process_id=execution_process_id,
                    )
            else:
                await self._emit_task_status(
                    task,
                    "failed",
                    result=task.result,
                    execution_process_id=execution_process_id,
                )

        workspace = await self.codex_store.load_codex_workspace(workspace_id)
        if workspace is not None:
            workspace.status = "idle"
            workspace.last_active_at = datetime.now()
            await self.codex_store.save_codex_workspace(workspace)
        return workspace

    async def terminate_task(self, task_id: str) -> None:
        """Kill a specific task process."""
        owned = False
        for process_key, entry in list(self._processes.items()):
            # Check if this entry belongs to the target task
            is_match = process_key == task_id
            if hasattr(entry, "task_id") and entry.task_id == task_id:
                is_match = True

            if is_match and self._owns_entry(entry):
                owned = True
                self._processes.pop(process_key, None)
                await self._cleanup_entry(process_key, entry)

        # Update task + execution-process status in DB. Previously this only
        # updated `task.status`, leaving the execution_process row at
        # "running" — the UI's run/status badge is derived from the EP so it
        # kept showing "Running" even though the task was killed.
        task = await self.codex_store.load_codex_task(task_id)
        if task and owned and not is_task_terminal_status(task.status):
            task.status = "failed"
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)

            execution_process_id = getattr(task, "last_execution_process_id", None)
            if execution_process_id:
                with suppress(Exception):
                    await self.codex_store.update_execution_process_status(
                        execution_process_id,
                        "Killed",
                        exit_code=None,
                        completed_at=datetime.now(),
                    )

            if self._event_bus:
                await self._emit_task_status(
                    task,
                    "failed",
                    result=task.result,
                    execution_process_id=execution_process_id,
                )
            else:
                await self._emit_task_status(
                    task,
                    "failed",
                    result=task.result,
                    execution_process_id=execution_process_id,
                )

    async def _is_chat_execution_process(self, execution_process_id: str | None) -> bool:
        if not execution_process_id or not hasattr(self.codex_store, "load_execution_process"):
            return False
        try:
            ep = await self.codex_store.load_execution_process(execution_process_id)
            return ep is not None and getattr(ep, "kind", "initial") == "chat"
        except Exception:
            return False

    async def _emit_task_status(
        self,
        task: CodexTask,
        status: str,
        *,
        result: str | None = None,
        review_comment: str | None = None,
        execution_process_id: str | None = None,
    ) -> None:
        from app.application.task_status_events import build_task_status_event

        status_event = build_task_status_event(
            task,
            status,
            result=result,
            review_comment=review_comment,
            execution_process_id=execution_process_id,
        )
        if self._event_bus is not None:
            await self._event_bus.append(status_event)
            return
        try:
            from app.interfaces.codex_ws import (
                message_stream_manager,
                raw_log_stream_manager,
                stream_manager,
            )

            await stream_manager.update_task_status(
                task.session_id,
                task.id,
                status,
                result,
                execution_process_id=execution_process_id,
                fallback_event=status_event,
            )
            if execution_process_id and is_task_terminal_status(status):
                await message_stream_manager.publish_finished(execution_process_id)
                await raw_log_stream_manager.publish_finished(execution_process_id)
        except Exception:
            logger.debug("task status stream update failed: task_id=%s", task.id, exc_info=True)

    async def terminate_all(self) -> list[str]:
        terminated = []
        for process_key, entry in list(self._processes.items()):
            if not self._owns_entry(entry):
                continue
            try:
                self._processes.pop(process_key, None)
                await self._cleanup_entry(process_key, entry)
                workspace = await self.codex_store.load_codex_workspace(entry.workspace_id)
                if workspace:
                    workspace.status = "idle"
                    workspace.last_active_at = datetime.now()
                    await self.codex_store.save_codex_workspace(workspace)
                terminated.append(process_key)
            except Exception:
                logger.debug("process cleanup failed: process_key=%s", process_key, exc_info=True)
        return terminated

    def _owns_entry(self, entry: AsyncProcessEntry) -> bool:
        raise NotImplementedError

    def _get_log_path(self, workspace_id: str) -> str:
        return f"{self._data_dir}/codex_session_{workspace_id}.log"

    async def _load_runtime_task_context(self, task_id: str) -> RuntimeTaskContext:
        task = await self.codex_store.load_codex_task(task_id)
        if task is None:
            return RuntimeTaskContext()
        return RuntimeTaskContext(
            execution_process_id=task.last_execution_process_id,
            trace_id=task.trace_id,
            span_id=task.span_id,
            parent_span_id=task.parent_span_id,
            issue_id=task.issue_id,
            is_workspace_console=is_workspace_console_task(task),
        )

    async def _ensure_entry_task_context(
        self,
        entry: AsyncProcessEntry,
        task_id: str | None,
    ) -> RuntimeTaskContext | None:
        if entry.task_context is None and task_id is not None:
            entry.task_context = await self._load_runtime_task_context(task_id)
        return entry.task_context

    async def _emit_message_delta(
        self,
        workspace_id: str,
        task_id: str | None,
        seq: int,
        delta_text: str,
        *,
        task_context: RuntimeTaskContext | None = None,
    ) -> None:
        """Resolve the task's current execution_process_id and broadcast a message_delta event.

        Skips silently if no event_bus or no resolvable execution_process_id."""
        if self._event_bus is None or not task_id:
            return
        if task_context is None:
            try:
                task_context = await self._load_runtime_task_context(task_id)
            except Exception:
                task_context = None
        execution_process_id = task_context.execution_process_id if task_context else None
        if not execution_process_id:
            return
        await self._event_bus.append(
            {
                "type": "message_delta",
                "execution_process_id": execution_process_id,
                "task_id": task_id,
                "session_id": workspace_id,
                "seq": seq,
                "delta_text": delta_text,
            }
        )

    async def _append_log(
        self,
        workspace_id: str,
        stream: str,
        content: str,
        task_id: str | None,
        *,
        task_context: RuntimeTaskContext | None = None,
    ) -> None:
        if task_context is None and task_id is not None:
            task_context = await self._load_runtime_task_context(task_id)
        execution_process_id = task_context.execution_process_id if task_context else None
        trace_id = task_context.trace_id if task_context else None
        span_id = task_context.span_id if task_context else None
        parent_span_id = task_context.parent_span_id if task_context else None
        created_at = datetime.now()
        event = LogEvent(
            id=f"log-{workspace_id}-{datetime.now().timestamp()}",
            session_id=workspace_id,
            stream=stream,
            content=content,
            task_id=task_id,
            execution_process_id=execution_process_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            created_at=created_at,
        )

        if self._event_bus is not None:
            await self._event_bus.queue_log_event(event)
            await self._event_bus.append(
                {
                    "type": "log",
                    "id": event.id,
                    "session_id": workspace_id,
                    "workspace_id": workspace_id,
                    "stream": stream,
                    "content": content,
                    "task_id": task_id,
                    "execution_process_id": execution_process_id,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "parent_span_id": parent_span_id,
                    "created_at": created_at.isoformat(),
                }
            )
        else:
            await self.log_store.append_log_event(event)

    async def _log_help_request_outcome(
        self,
        workspace_id: str,
        task_id: str | None,
        outcome: str,
        detail: str,
    ) -> None:
        message = f"request_help {outcome}: {detail}"
        logger.info(
            "help request outcome: workspace_id=%s task_id=%s %s",
            workspace_id,
            task_id,
            message,
        )
        await self._append_log(workspace_id, "help_request", message, task_id)

    async def _list_task_messages(
        self,
        task_id: str,
        execution_process_id: str | None = None,
    ) -> list[CodexTaskMessage]:
        if execution_process_id:
            try:
                return await self.codex_store.list_codex_task_messages(
                    task_id,
                    execution_process_id=execution_process_id,
                )
            except TypeError:
                pass
        return await self.codex_store.list_codex_task_messages(task_id)

    async def _list_runtime_log_events(
        self,
        task: CodexTask,
        execution_process_id: str | None,
    ) -> list[LogEvent]:
        loader = getattr(self.log_store, "load_log_events", None) or getattr(
            self.codex_store,
            "load_log_events",
            None,
        )
        if not callable(loader):
            return []
        try:
            result = loader(
                task.session_id,
                task_id=task.id,
                execution_process_id=execution_process_id,
                limit=500,
                reverse=False,
            )
            events = await result if inspect.isawaitable(result) else result
            return list(events) if events else []
        except Exception:
            logger.debug("runtime trace log load failed: task_id=%s", task.id, exc_info=True)
            return []

    async def _persist_runtime_agent_trace(
        self,
        task: CodexTask,
        execution_process_id: str | None,
        entry: AsyncProcessEntry,
        *,
        process_status: str,
        exit_code: int | None,
    ) -> None:
        save_trace = getattr(self.codex_store, "save_agent_call_trace", None)
        if not callable(save_trace):
            return
        try:
            messages = await self._list_task_messages(
                task.id,
                execution_process_id=execution_process_id,
            )
            logs = await self._list_runtime_log_events(task, execution_process_id)
            request_payload = {
                "task_id": task.id,
                "title": task.title,
                "role": task.role,
                "task_kind": task.task_kind,
                "prompt": task.prompt,
                "executor": task.executor,
                "provider": task.provider,
                "model": task.model,
                "workspace_id": task.session_id,
                "workspace_path": task.workspace_path,
            }
            response_payload = {
                "status": task.status,
                "process_status": process_status,
                "exit_code": exit_code,
                "result": task.result or entry.result_text,
                "messages": [
                    {
                        "id": message.id,
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat()
                        if message.created_at
                        else None,
                    }
                    for message in messages
                ],
                "logs": [
                    {
                        "id": event.id,
                        "stream": event.stream,
                        "content": event.content,
                        "created_at": event.created_at.isoformat() if event.created_at else None,
                    }
                    for event in logs
                ],
            }
            trace_title = f"{task.role or 'Agent'} · {task.title}"
            request_json, request_preview, request_truncated = _runtime_trace_json_and_preview(
                request_payload
            )
            response_json, response_preview, response_truncated = _runtime_trace_json_and_preview(
                response_payload
            )
            trace_key = execution_process_id or task.last_execution_process_id or task.id
            trace_metadata: dict[str, object] = {
                "source": "runtime_agent_snapshot",
                "executor": task.executor,
                "provider": task.provider,
                "model": task.model,
                "message_count": len(messages),
                "log_count": len(logs),
                "process_status": process_status,
                "exit_code": exit_code,
            }
            result = save_trace(
                AgentCallTrace(
                    id=f"runtime-trace-{trace_key}",
                    trace_id=task.trace_id,
                    span_id=task.span_id,
                    parent_span_id=task.parent_span_id,
                    issue_id=task.issue_id,
                    task_id=task.id,
                    execution_process_id=execution_process_id,
                    kind="runtime_agent",
                    title=trace_title,
                    request_json=request_json,
                    response_json=response_json,
                    request_preview=request_preview,
                    response_preview=response_preview,
                    metadata_json=json.dumps(trace_metadata, ensure_ascii=False, default=str),
                    is_truncated=request_truncated or response_truncated,
                    created_at=datetime.now(),
                )
            )
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.debug("runtime agent trace recording failed: task_id=%s", task.id, exc_info=True)

    async def _capture_on_reader(
        self,
        workspace_id: str,
        line: str,
        entry: AsyncProcessEntry,
        task_id: str | None,
    ) -> None:
        parsed = self._try_parse_json(line)
        if parsed is None:
            return
        task_context = await self._ensure_entry_task_context(entry, task_id)
        await self._maybe_persist_usage(task_id, parsed, task_context=task_context)

        if task_id and self.help_orchestrator is not None:
            from app.application.help_event_parser import parse_help_request_event

            help_event = parse_help_request_event(parsed, executor=entry.executor)
            if help_event is not None:
                task = await self.codex_store.load_codex_task(task_id)
                if task is not None and not is_task_active_status(task.status):
                    await self._log_help_request_outcome(
                        workspace_id,
                        task_id,
                        "rejected",
                        f"task status is {task.status}",
                    )
                    help_event = None

            if help_event is not None:
                try:
                    await self.help_orchestrator.request_help_from_runtime(
                        task_id=task_id,
                        workspace_id=workspace_id,
                        **help_event,
                    )
                    await self._log_help_request_outcome(
                        workspace_id,
                        task_id,
                        "accepted",
                        f"target={help_event['target_executor']} title={help_event['title']}",
                    )
                    entry.help_requested = True
                    return
                except Exception as exc:
                    await self._log_help_request_outcome(
                        workspace_id,
                        task_id,
                        "rejected",
                        str(exc),
                    )

        msg_type = parsed.get("type")
        if not msg_type:
            return

        # Log every LLM token stream event in real-time
        if msg_type == "stream_event":
            evt = object_dict(parsed.get("event"))
            delta = object_dict(evt.get("delta"))
            dt = string_value(delta.get("type"))
            delta_text = string_value(delta.get("text"))
            delta_thinking = string_value(delta.get("thinking"))
            delta_preview = delta_text or delta_thinking
            logger.debug(
                "[LLM token] task=%s delta_type=%s chars=%d preview=%s",
                task_id,
                dt,
                len(delta_preview),
                delta_preview[:100],
            )
            # Feed the stall watchdog: any token (even empty-delta keep-alives)
            # counts as live progress and resets the silence timer.
            from app.application import task_activity

            task_activity.touch(task_id)

        session_id_val = parsed.get("session_id")
        if isinstance(session_id_val, str) and session_id_val and entry.resume_session_id is None:
            entry.resume_session_id = session_id_val
            # The per-workspace thread pointer is only for the human console chat.
            # Role/help tasks keep their session on the task alone (per-task
            # identity), so they never pollute the shared pointer.
            if task_context is None or task_context.is_workspace_console:
                workspace = await self.codex_store.load_codex_workspace(workspace_id)
                if workspace:
                    if entry.executor == "codex":
                        workspace.thread_id = session_id_val
                    elif entry.executor == "claude":
                        workspace.claude_thread_id = session_id_val
                    elif entry.executor == "acp":
                        # ACP session ids live on the task only; never on the
                        # shared workspace thread pointers (codex/claude).
                        pass
                    await self.codex_store.save_codex_workspace(workspace)

        if msg_type == "system":
            return

        if msg_type == "assistant":
            assistant_uuid = parsed.get("uuid")
            if isinstance(assistant_uuid, str) and assistant_uuid:
                entry.resume_message_id = assistant_uuid
            msg = object_dict(parsed.get("message"))
            content = msg.get("content", [])
            if isinstance(content, list):
                text_parts: list[str] = []
                display_parts: list[str] = []
                for raw_item in content:
                    item = object_dict(raw_item)
                    item_type = item.get("type")
                    if item_type == "text":
                        text = string_value(item.get("text"))
                        if text:
                            text_parts.append(text)
                            display_parts.append(text)
                            entry.last_activity_kind = "text"
                    elif item_type == "thinking":
                        thinking = string_value(item.get("thinking"))
                        if thinking:
                            thinking_payload = json.dumps(
                                {"text": thinking},
                                ensure_ascii=False,
                                default=str,
                            )
                            await self._append_log(
                                workspace_id,
                                "thinking",
                                thinking_payload,
                                task_id,
                                task_context=task_context,
                            )
                            entry.last_activity_kind = "reasoning"
                    elif item_type == "tool_use":
                        tool_use_id = string_value(item.get("id") or item.get("tool_use_id"))
                        if tool_use_id and tool_use_id in entry.emitted_tool_use_ids:
                            continue
                        if tool_use_id:
                            entry.emitted_tool_use_ids.add(tool_use_id)
                        tool_name_val = string_value(item.get("name") or item.get("tool_name"))
                        payload = json.dumps(
                            {
                                "kind": "tool_use",
                                "tool_use_id": tool_use_id,
                                "tool_name": tool_name_val,
                                "input": item.get("input") or {},
                            },
                            ensure_ascii=False,
                            default=str,
                        )
                        await self._append_log(
                            workspace_id,
                            "tool_use",
                            payload,
                            task_id,
                            task_context=task_context,
                        )
                        entry.last_activity_kind = "tool"
                        await self._maybe_emit_worktree_dirty(
                            workspace_id,
                            task_id,
                            entry,
                            tool_name_val,
                            task_context=task_context,
                        )
                if display_parts:
                    new_display = "".join(display_parts).strip()
                    if new_display and new_display != entry.last_emitted_assistant_text:
                        last = entry.last_emitted_assistant_text
                        if new_display.startswith(last):
                            message_delta = new_display[len(last) :]
                        else:
                            message_delta = new_display
                        if message_delta:
                            entry.delta_seq += 1
                            entry.last_emitted_assistant_text = new_display
                            await self._emit_message_delta(
                                workspace_id,
                                task_id,
                                entry.delta_seq,
                                message_delta,
                                task_context=task_context,
                            )
                            import logging as _ldelta

                            _ldelta.getLogger(__name__).info(
                                "[LLM stream] task=%s seq=%d chars=%d\n%s",
                                task_id,
                                entry.delta_seq,
                                len(message_delta),
                                message_delta,
                            )
                if text_parts:
                    entry.result_text = "".join(text_parts).strip()
                    entry.produced_real_turn = True
            return

        if msg_type == "user":
            # Claude stream-json emits tool_result entries inside a "user" turn.
            # Surface them as structured tool_result logs so the UI can fold
            # them onto the matching tool_use card.
            msg = object_dict(parsed.get("message"))
            content = msg.get("content", [])
            if isinstance(content, list):
                for raw_item in content:
                    item = object_dict(raw_item)
                    if item.get("type") != "tool_result":
                        continue
                    tool_use_id = string_value(item.get("tool_use_id") or item.get("id"))
                    if tool_use_id and tool_use_id in entry.emitted_tool_result_ids:
                        continue
                    if tool_use_id:
                        entry.emitted_tool_result_ids.add(tool_use_id)
                    raw_content = item.get("content")
                    if isinstance(raw_content, list):
                        text_chunks: list[str] = []
                        for piece in raw_content:
                            piece_text = object_dict(piece).get("text")
                            if isinstance(piece_text, str):
                                text_chunks.append(piece_text)
                            elif isinstance(piece, str):
                                text_chunks.append(piece)
                        result_text = "\n".join(text_chunks)
                    elif isinstance(raw_content, str):
                        result_text = raw_content
                    else:
                        result_text = ""
                    payload = json.dumps(
                        {
                            "kind": "tool_result",
                            "tool_use_id": tool_use_id,
                            "output": result_text,
                            "is_error": bool(item.get("is_error")),
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                    await self._append_log(
                        workspace_id,
                        "tool_result",
                        payload,
                        task_id,
                        task_context=task_context,
                    )
            return

        if msg_type == "tool_use":
            tool_name_val = string_value(parsed.get("tool_name") or parsed.get("name"))
            tool_use_id_val = string_value(parsed.get("tool_use_id") or parsed.get("id"))
            tool_input = parsed.get("input") or {}
            input_preview = str(tool_input)[:80]
            logger.info(
                "[tool_use] task=%s tool=%s id=%s input=%s",
                task_id,
                tool_name_val,
                tool_use_id_val[:8],
                input_preview,
            )
            payload = json.dumps(
                {
                    "kind": "tool_use",
                    "tool_use_id": tool_use_id_val,
                    "tool_name": tool_name_val,
                    "input": tool_input,
                },
                ensure_ascii=False,
                default=str,
            )
            await self._append_log(
                workspace_id,
                "tool_use",
                payload,
                task_id,
                task_context=task_context,
            )
            entry.last_activity_kind = "tool"
            await self._maybe_emit_worktree_dirty(
                workspace_id,
                task_id,
                entry,
                tool_name_val,
                task_context=task_context,
            )
            return

        if msg_type == "tool_result":
            tool_result_id = string_value(parsed.get("tool_use_id") or parsed.get("id"))
            is_error = bool(parsed.get("is_error"))
            logger.info(
                "[tool_result] task=%s id=%s error=%s", task_id, tool_result_id[:8], is_error
            )
            payload = json.dumps(
                {
                    "kind": "tool_result",
                    "tool_use_id": tool_result_id,
                    "output": parsed.get("result")
                    if isinstance(parsed.get("result"), str)
                    else parsed.get("output", ""),
                    "is_error": is_error,
                },
                ensure_ascii=False,
                default=str,
            )
            await self._append_log(
                workspace_id,
                "tool_result",
                payload,
                task_id,
                task_context=task_context,
            )
            return

        if msg_type == "result":
            _terminal_reason = parsed.get("terminal_reason", "")
            if (
                parsed.get("is_error")
                or parsed.get("subtype") == "error_during_execution"
                or _terminal_reason in {"aborted_streaming", "error", "interrupted"}
            ):
                entry.had_error = True
            result_val = parsed.get("result")
            if isinstance(result_val, str) and result_val.strip():
                if not is_cli_control_payload(result_val):
                    entry.result_text = result_val.strip()
                    entry.produced_real_turn = True
            elif isinstance(result_val, dict):
                result_obj = object_dict(result_val)
                result_text_value = result_obj.get("text") or result_obj.get("content") or ""
                if result_text_value:
                    text_str = (
                        result_text_value
                        if isinstance(result_text_value, str)
                        else str(result_text_value)
                    )
                    if not is_cli_control_payload(text_str):
                        entry.result_text = text_str
                        entry.produced_real_turn = True
            return

        if msg_type == "item.completed":
            item = object_dict(parsed.get("item"))
            if is_agent_message_item_type(string_value(item.get("type"))):
                value = item.get("text")
                if isinstance(value, str) and value.strip() and not is_cli_control_payload(value):
                    entry.result_text = value.strip()
                    entry.produced_real_turn = True

    async def _maybe_persist_usage(
        self,
        task_id: str | None,
        parsed: object,
        *,
        task_context: RuntimeTaskContext | None = None,
    ) -> None:
        if not task_id or not hasattr(self.codex_store, "update_execution_process_usage"):
            return
        usage = extract_usage(parsed)
        if not usage:
            return

        input_tokens = read_usage_int(usage, "input_tokens", "prompt_tokens")
        output_tokens = read_usage_int(usage, "output_tokens", "completion_tokens")
        cache_read_tokens = read_usage_int(
            usage,
            "cache_read_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        total_cost_usd = read_usage_float(usage, "total_cost_usd")
        if total_cost_usd is None:
            total_cost_usd = price_tokens(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
            )
        try:
            if task_context is None:
                task_context = await self._load_runtime_task_context(task_id)
            execution_process_id = task_context.execution_process_id
            if execution_process_id:
                await self.codex_store.update_execution_process_usage(
                    execution_process_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    total_cost_usd=total_cost_usd,
                )
        except Exception:
            logger.debug(
                "execution process usage update failed: task_id=%s", task_id, exc_info=True
            )

    async def _mark_task_done(self, task_id: str, entry: AsyncProcessEntry) -> None:
        if entry.help_requested:
            return
        task = await self.codex_store.load_codex_task(task_id)
        if task:
            execution_process_id = task.last_execution_process_id
            # Branch on EP kind: chat runs must NOT mutate task.result and must
            # NOT trigger artifact persistence. The assistant reply is captured
            # in the message log only.
            is_chat = await self._is_chat_execution_process(execution_process_id)

            task.status = "done"
            if (
                not is_chat and entry.result_text and not is_unusable_result_text(entry.result_text)
            ):
                task.result = entry.result_text
            task.updated_at = datetime.now()

            import logging as _logging

            _logger = _logging.getLogger(__name__)

            if not is_chat and callable(self.refresh_task_result):
                try:
                    await self.refresh_task_result(task)
                except Exception as exc:
                    _logger.error(
                        "refresh_task_result failed for task %s, raw response was: %s",
                        task_id,
                        task.result,
                    )
                    entry.had_error = True
                    entry.result_text = str(exc)
                    await self._mark_task_failed(task_id, entry)
                    return

            fresh = await self.codex_store.load_codex_task(task.id)
            if fresh is not None and (
                is_task_failure_status(fresh.status)
                or fresh.status in ("waiting_for_specialist", "waiting_for_help")
            ):
                task = fresh

            process_status, process_exit_code = execution_process_state_for_task(task.status)
            if execution_process_id:
                await self.codex_store.update_execution_process_status(
                    execution_process_id,
                    process_status,
                    exit_code=process_exit_code,
                    completed_at=datetime.now() if is_task_terminal_status(task.status) else None,
                )
            await self.codex_store.save_codex_task(task)
            # For chat runs the agent reply is plain natural language — show it as-is.
            # For initial/rerun/refine the agent returns raw schema JSON which the
            # role workflow rewrites into a human-readable summary on task.result;
            # surface that summary instead of dumping JSON to the chat thread.
            assistant_text = entry.result_text if is_chat else (task.result or entry.result_text)
            # Chat-mode safety net: weak instruction-following models sometimes
            # ignore our "do not output JSON" directive and reply with the full
            # role artifact JSON anyway. Detect that and replace with a hint
            # rather than dumping a JSON blob into the chat thread.
            if is_chat and assistant_text:
                assistant_text = _sanitize_chat_reply(assistant_text)
            await self._persist_assistant_message(task_id, execution_process_id, assistant_text)
            await self._persist_runtime_agent_trace(
                task,
                execution_process_id,
                entry,
                process_status=process_status,
                exit_code=process_exit_code,
            )

            await self._emit_task_status(
                task,
                task.status,
                result=task.result,
                review_comment=getattr(task, "review_comment", None),
                execution_process_id=execution_process_id,
            )

            await self._complete_help_child_if_needed(
                task,
                child_status=task.status,
                child_result=task.result,
            )

    async def _mark_task_failed(self, task_id: str, entry: AsyncProcessEntry) -> None:
        if entry.help_requested:
            return
        task = await self.codex_store.load_codex_task(task_id)
        if task is None:
            return

        execution_process_id = task.last_execution_process_id
        task.status = "failed"
        if entry.result_text and not is_unusable_result_text(entry.result_text):
            task.result = entry.result_text
        task.updated_at = datetime.now()
        await self.codex_store.save_codex_task(task)

        if execution_process_id:
            exit_code = getattr(entry.proc, "returncode", None)
            await self.codex_store.update_execution_process_status(
                execution_process_id,
                "Failed",
                exit_code=exit_code,
                completed_at=datetime.now(),
            )

        await self._persist_runtime_agent_trace(
            task,
            execution_process_id,
            entry,
            process_status="Failed",
            exit_code=getattr(entry.proc, "returncode", None),
        )

        if self._event_bus is not None:
            await self._emit_task_status(
                task,
                task.status,
                result=task.result,
                execution_process_id=execution_process_id,
            )
        else:
            await self._emit_task_status(
                task,
                task.status,
                result=task.result,
                execution_process_id=execution_process_id,
            )
        await self._complete_help_child_if_needed(
            task, child_status="failed", child_result=task.result
        )

    async def _persist_assistant_message(
        self,
        task_id: str,
        execution_process_id: str | None,
        content: str | None,
    ) -> None:
        if not task_id or not execution_process_id or not content:
            return

        from app.domain.models import CodexTaskMessage

        text = content.strip()
        if not text:
            return

        existing = await self._list_task_messages(
            task_id, execution_process_id=execution_process_id
        )
        if existing and existing[-1].role == "assistant" and existing[-1].content == text:
            return

        message = CodexTaskMessage(
            id=str(uuid4()),
            task_id=task_id,
            execution_process_id=execution_process_id,
            role="assistant",
            content=text,
            created_at=datetime.now(),
        )
        await self.codex_store.save_codex_task_message(message)

        if self._event_bus is not None:
            await self._event_bus.append(
                {
                    "type": "message_created",
                    "execution_process_id": execution_process_id,
                    "message": {
                        "id": message.id,
                        "task_id": message.task_id,
                        "execution_process_id": message.execution_process_id,
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat()
                        if message.created_at
                        else None,
                    },
                }
            )

    async def _persist_reader_metadata(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
    ) -> None:
        task = await self.codex_store.load_codex_task(task_id) if task_id else None
        is_console = task is None or is_workspace_console_task(task)

        workspace = await self.codex_store.load_codex_workspace(workspace_id)
        if workspace:
            # Only the human console task may update the shared per-workspace
            # thread pointer; role/help tasks keep their session on the task.
            if entry.resume_session_id and is_console:
                if entry.executor == "codex":
                    workspace.thread_id = entry.resume_session_id
                elif entry.executor == "claude":
                    workspace.claude_thread_id = entry.resume_session_id
                elif entry.executor == "acp":
                    # ACP session ids are persisted on the task only; never
                    # mirror them onto the shared codex/claude thread pointers.
                    pass
            workspace.status = "idle"
            workspace.last_active_at = datetime.now()
            await self.codex_store.save_codex_workspace(workspace)

        if task_id and task:
            is_chat = await self._is_chat_execution_process(task.last_execution_process_id)
            if entry.resume_session_id and entry.produced_real_turn:
                # Only carry a session id that produced a real turn. A control-only
                # / empty run captured a session id that is effectively dead;
                # persisting it would make a retry resume the dead session and loop.
                task.resume_session_id = entry.resume_session_id
            elif not entry.produced_real_turn and not is_console:
                task.resume_session_id = None
            if entry.resume_message_id and entry.produced_real_turn:
                task.resume_message_id = entry.resume_message_id
            if (
                entry.result_text
                and not is_task_terminal_status(task.status)
                and not is_unusable_result_text(entry.result_text)
                and not is_chat
                and not entry.had_error
                and not entry.idle_timed_out
            ):
                task.result = entry.result_text
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)

    async def _finalize_task_on_reader_exit(
        self,
        task_id: str | None,
        entry: AsyncProcessEntry,
    ) -> None:
        if not task_id or entry.help_requested:
            return

        task = await self.codex_store.load_codex_task(task_id)
        if task is None or is_task_terminal_status(task.status):
            return

        import logging as _log2

        _logger = _log2.getLogger(__name__)

        execution_process_id = task.last_execution_process_id
        is_chat = await self._is_chat_execution_process(execution_process_id)
        exit_code = getattr(entry.proc, "returncode", None)
        fallback_result = None
        if not entry.result_text and not entry.had_error:
            fallback_result = await self._build_idle_timeout_fallback_result(task, entry)
            if fallback_result:
                entry.result_text = fallback_result
        if entry.idle_timed_out and not fallback_result:
            entry.had_error = True

        if entry.had_error:
            task.status = "failed"
        elif entry.result_text or exit_code == 0:
            task.status = "done"
            if (
                entry.result_text and not is_unusable_result_text(entry.result_text) and not is_chat
            ):
                task.result = entry.result_text
            task.updated_at = datetime.now()

            # Call refresh_task_result to persist artifacts
            if not is_chat and callable(self.refresh_task_result):
                try:
                    await self.refresh_task_result(task)
                except Exception as exc:
                    _logger.error(
                        "refresh_task_result failed for task %s, raw response was: %s",
                        task_id,
                        entry.result_text,
                    )
                    task.status = "failed"
                    task.result = str(exc)

        else:
            task.status = "failed"
            if entry.idle_timed_out:
                timeout_seconds = entry.idle_timeout_seconds or "unknown"
                task.result = (
                    "Runtime went idle before emitting a final result "
                    f"(idle timeout: {timeout_seconds} seconds)."
                )

        task.updated_at = datetime.now()

        # Reload from DB: refresh_task_result may have triggered a specialist
        # request that changed task.status in the DB. Saving our stale local
        # copy would overwrite that state.
        fresh = await self.codex_store.load_codex_task(task.id)
        if fresh is not None and (
            is_task_failure_status(fresh.status)
            or fresh.status in ("waiting_for_specialist", "waiting_for_help")
        ):
            task = fresh

        process_status, projected_exit_code = execution_process_state_for_task(task.status)
        final_exit_code = projected_exit_code
        if process_status == "Failed" and exit_code not in (None, 0):
            final_exit_code = exit_code

        await self.codex_store.save_codex_task(task)

        if execution_process_id:
            await self.codex_store.update_execution_process_status(
                execution_process_id,
                process_status,
                exit_code=final_exit_code,
                completed_at=datetime.now() if is_task_terminal_status(task.status) else None,
            )

        await self._emit_task_status(
            task,
            task.status,
            result=task.result,
            execution_process_id=execution_process_id,
        )
        await self._persist_runtime_agent_trace(
            task,
            execution_process_id,
            entry,
            process_status=process_status,
            exit_code=final_exit_code,
        )
        await self._complete_help_child_if_needed(
            task, child_status=task.status, child_result=task.result
        )

    async def _complete_help_child_if_needed(
        self,
        task: CodexTask | None,
        *,
        child_status: str,
        child_result: str | None,
    ) -> None:
        if self.help_orchestrator is None or task is None:
            return
        if task.task_kind != "help_child" or not task.blocked_by_help_id:
            return

        help_request = await self.codex_store.load_help_request(task.blocked_by_help_id)
        if help_request is None or is_help_request_terminal_status(help_request.status):
            return

        normalized_status = "done" if is_task_success_status(child_status) else "failed"
        await self.help_orchestrator.complete_help_request(
            task.blocked_by_help_id,
            child_status=normalized_status,
            child_result=child_result,
        )

    def _try_parse_json(self, line: str) -> dict[str, object] | None:
        stripped = line.strip()
        if not stripped.startswith("{"):
            return None
        try:
            parsed = json.loads(stripped)
            if not isinstance(parsed, dict):
                return None
            return {str(key): value for key, value in parsed.items()}
        except (json.JSONDecodeError, TypeError):
            return None

    async def _build_idle_timeout_fallback_result(
        self,
        task: CodexTask,
        entry: AsyncProcessEntry,
    ) -> str | None:
        """Recover engineer output when the runtime stalls after file changes."""
        if not entry.idle_timed_out or entry.had_error:
            return None
        if task.role != "engineer":
            return None
        if not task.workspace_path:
            return None

        try:
            from app.application.engineer_workflow import EngineerWorkflow

            changed_files = EngineerWorkflow()._git_changed_files(task.workspace_path)
        except Exception:
            return None
        if not changed_files:
            return None

        workspace_title = "workspace-project"
        try:
            workspace = await self.codex_store.load_codex_workspace(task.session_id)
        except Exception:
            workspace = None
        if workspace is not None and getattr(workspace, "title", None):
            workspace_title = workspace.title

        payload = {
            "language": "en",
            "project_name": workspace_title,
            "issue_id": task.issue_id or task.id,
            "issue_title": task.title,
            "status": "partial",
            "summary": (
                "Framework fallback recovered the engineer output after the runtime "
                f"went idle for {entry.idle_timeout_seconds or 'an unknown number of'} seconds "
                "before emitting the final JSON report."
            ),
            "changed_files": changed_files,
            "completed_tasks": [],
            "deferred_tasks": [],
            "risks": [
                "The engineer runtime stalled after applying code changes, so this report was synthesized from git state.",
            ],
            "verification_commands": [],
            "qa_notes": [
                "Review the changed files carefully because the engineer did not emit its normal structured completion report.",
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    # --- Async Process Management ---

    async def _terminate_process_tree(
        self,
        proc: asyncio.subprocess.Process | None,
        *,
        grace_s: float = 2.0,
    ) -> None:
        if proc is None or getattr(proc, "returncode", None) is not None:
            return
        pid = getattr(proc, "pid", None)
        sent_group_signal = False
        if pid and os.name != "nt":
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                sent_group_signal = True
            except Exception:
                sent_group_signal = False
        if not sent_group_signal:
            with suppress(Exception):
                proc.terminate()
        with suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=grace_s)
            return
        if pid and os.name != "nt":
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                sent_group_signal = True
            except Exception:
                sent_group_signal = False
        if not sent_group_signal:
            with suppress(Exception):
                proc.kill()
        with suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=grace_s)

    async def _watchdog(
        self,
        workspace_id: str,
        entry: AsyncProcessEntry,
        task_id: str | None,
        timeout_sec: int,
    ) -> None:
        try:
            await asyncio.sleep(timeout_sec)
            if not entry.alive:
                return
            entry.alive = False
            if entry.proc:
                await self._terminate_process_tree(entry.proc)
            if task_id:
                task = await self.codex_store.load_codex_task(task_id)
                if task and not is_task_terminal_status(task.status):
                    task.status = "failed"
                    task.result = f"Process exceeded maximum timeout of {timeout_sec} seconds"
                    task.updated_at = datetime.now()
                    await self.codex_store.save_codex_task(task)
                    execution_process_id = task.last_execution_process_id
                    if execution_process_id:
                        with suppress(Exception):
                            await self.codex_store.update_execution_process_status(
                                execution_process_id,
                                "Failed",
                                exit_code=None,
                                completed_at=datetime.now(),
                            )
                    await self._emit_task_status(
                        task,
                        "failed",
                        result=task.result,
                        execution_process_id=execution_process_id,
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug(
                "reader loop task failure marking failed: task_id=%s", task_id, exc_info=True
            )

    # Tool names that mutate the worktree. Matched case-insensitively. Keep
    # tight — we don't want every `Bash` to retrigger diff fetches.
    _WORKTREE_WRITE_TOOLS = frozenset(
        {
            "apply_patch",
            "edit",
            "write",
            "multiedit",
            "notebookedit",
            "applypatch",
            "str_replace_editor",
        }
    )

    async def _maybe_emit_worktree_dirty(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
        tool_name: str,
        *,
        task_context: RuntimeTaskContext | None = None,
    ) -> None:
        """Throttled emit of worktree_dirty so the diff/git panels refetch
        while engineer is writing. 5s window between emits per process."""
        if self._event_bus is None or not task_id or not tool_name:
            return
        if tool_name.lower() not in self._WORKTREE_WRITE_TOOLS:
            return
        import time as _time

        now = _time.monotonic()
        if now - entry.last_worktree_dirty_at < 5.0:
            return
        entry.last_worktree_dirty_at = now
        # Cache issue_id off the task to avoid hitting the store every emit.
        if entry.cached_issue_id is None:
            if task_context is not None:
                entry.cached_issue_id = task_context.issue_id
            else:
                try:
                    task = await self.codex_store.load_codex_task(task_id)
                    entry.cached_issue_id = task.issue_id if task is not None else None
                except Exception:
                    entry.cached_issue_id = None
        if not entry.cached_issue_id:
            return
        with suppress(Exception):
            await self._event_bus.append(
                {
                    "type": "worktree_dirty",
                    "issue_id": entry.cached_issue_id,
                    "session_id": workspace_id,
                    "task_id": task_id,
                    "tool_name": tool_name,
                    "created_at": datetime.now().isoformat(),
                }
            )

    async def _heartbeat_loop(
        self,
        workspace_id: str,
        entry: AsyncProcessEntry,
        task_id: str | None,
    ) -> None:
        """Periodic heartbeat so AgentLiveTimeline can render a live phase + elapsed
        counter even when stdout is quiet. Emits via event_bus → raw_log_stream_manager."""
        import time as _time

        interval = 5.0
        while entry.alive:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return
            if not entry.alive:
                return
            if self._event_bus is None or not task_id:
                continue
            try:
                task_context = await self._ensure_entry_task_context(entry, task_id)
            except Exception:
                task_context = None
            execution_process_id = (
                task_context.execution_process_id if task_context is not None else None
            )
            if not execution_process_id:
                continue
            now = _time.monotonic()
            last = entry.last_event_at or now
            elapsed_ms = max(0, int((now - last) * 1000))
            with suppress(Exception):
                await self._event_bus.append(
                    {
                        "type": "heartbeat",
                        "execution_process_id": execution_process_id,
                        "task_id": task_id,
                        "session_id": workspace_id,
                        "phase": entry.last_activity_kind or "idle",
                        "last_event_at": entry.last_event_at,
                        "elapsed_since_last_ms": elapsed_ms,
                        "created_at": datetime.now().isoformat(),
                    }
                )

    async def _reader_loop(
        self,
        workspace_id: str,
        entry: AsyncProcessEntry,
        task_id: str | None,
    ) -> None:
        """Async reader loop using await stdout.readline()."""
        import time as _time

        idle_timeout = timeouts.process_idle_timeout_s()
        max_timeout = entry.max_timeout_seconds or timeouts.process_max_timeout_s()
        entry.last_event_at = _time.monotonic()
        watchdog_task = asyncio.create_task(
            self._watchdog(workspace_id, entry, task_id, max_timeout)
        )
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(workspace_id, entry, task_id))
        stdout = entry.proc.stdout

        try:
            if stdout is None:
                entry.had_error = True
                if not entry.result_text:
                    entry.result_text = "Runtime process has no stdout pipe."
                return
            while entry.alive:
                try:
                    line = await asyncio.wait_for(stdout.readline(), timeout=idle_timeout)
                except TimeoutError:
                    entry.idle_timed_out = True
                    entry.idle_timeout_seconds = idle_timeout
                    break
                except Exception:
                    entry.had_error = True
                    if not entry.result_text:
                        entry.result_text = "Runtime reader failed before emitting a final result."
                    break
                if not line:
                    break

                entry.last_event_at = _time.monotonic()
                decoded = line.decode("utf-8", errors="replace")
                task_context = await self._ensure_entry_task_context(entry, task_id)
                await self._append_log(
                    workspace_id,
                    "stdout",
                    decoded,
                    task_id,
                    task_context=task_context,
                )
                await self._capture_on_reader(workspace_id, decoded, entry, task_id)

                parsed = self._try_parse_json(decoded)
                if parsed and parsed.get("type") in ("turn.completed", "result"):
                    if task_id:
                        if parsed.get("type") == "result" and (
                            parsed.get("is_error") or entry.had_error
                        ):
                            # Hard aborts (aborted_streaming, error_during_execution) mean
                            # the stream was cut off mid-way — partial result_text is not a
                            # valid artifact, so always fail. For softer is_error (tool call
                            # failed but model finished), attempt to persist if content exists.
                            _is_hard_abort = parsed.get(
                                "subtype"
                            ) == "error_during_execution" or parsed.get("terminal_reason") in {
                                "aborted_streaming",
                                "error",
                                "interrupted",
                            }
                            if entry.result_text and not _is_hard_abort:
                                await self._mark_task_done(task_id, entry)
                            else:
                                await self._mark_task_failed(task_id, entry)
                        else:
                            await self._mark_task_done(task_id, entry)
                    # A synchronous caller may consume task.result immediately
                    # after this waiter fires. Release it only after the terminal
                    # task/result persistence above has completed.
                    for waiter in list(entry.pending_waiters):
                        waiter.set()
                    entry.pending_waiters.clear()
        except Exception:
            logger.debug("reader loop finalization failed: task_id=%s", task_id, exc_info=True)
        finally:
            entry.alive = False
            with suppress(Exception):
                if entry.proc and entry.proc.returncode is None:
                    await self._terminate_process_tree(entry.proc)
            watchdog_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(watchdog_task), timeout=1)
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(heartbeat_task), timeout=1)

            try:
                stderr_reader = entry.proc.stderr
                if stderr_reader is not None:
                    stderr = await asyncio.wait_for(stderr_reader.read(), timeout=1)
                    if stderr:
                        task_context = await self._ensure_entry_task_context(entry, task_id)
                        await self._append_log(
                            workspace_id,
                            "stderr",
                            stderr.decode("utf-8", errors="replace"),
                            task_id,
                            task_context=task_context,
                        )
            except Exception:
                logger.debug("reader loop stderr drain failed: task_id=%s", task_id, exc_info=True)

            try:
                await self._persist_reader_metadata(workspace_id, task_id, entry)
            finally:
                try:
                    await self._finalize_task_on_reader_exit(task_id, entry)
                finally:
                    # EOF/error paths do not have a terminal frame. They must
                    # finalize persisted task state before waking wait=True callers.
                    for waiter in entry.pending_waiters:
                        waiter.set()
                    entry.pending_waiters.clear()

    async def _cleanup_entry(
        self,
        workspace_id: str,
        entry: ProcessEntry | AsyncProcessEntry,
    ) -> None:
        """Clean up a process entry (sync or async)."""
        try:
            entry.alive = False
            if hasattr(entry, "proc"):
                if isinstance(entry.proc, asyncio.subprocess.Process):
                    if entry.proc.stdin:
                        entry.proc.stdin.close()
                        with suppress(Exception):
                            await entry.proc.stdin.wait_closed()
                    await self._terminate_process_tree(entry.proc)
                elif isinstance(entry.proc, subprocess.Popen):
                    try:
                        entry.proc.terminate()
                        entry.proc.wait(timeout=2)
                    except Exception:
                        with suppress(Exception):
                            entry.proc.kill()
        except Exception:
            logger.debug(
                "process tree cleanup failed: workspace_id=%s", workspace_id, exc_info=True
            )

        if hasattr(entry, "output_task") and entry.output_task and not entry.output_task.done():
            entry.output_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(entry.output_task), timeout=1)
        if (
            hasattr(entry, "turn_watchdog_task")
            and entry.turn_watchdog_task
            and not entry.turn_watchdog_task.done()
        ):
            entry.turn_watchdog_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(entry.turn_watchdog_task), timeout=1)
