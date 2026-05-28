import asyncio
import json
import os
import sys
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.domain.models import LogEvent


def is_agent_message_item_type(item_type: str | None) -> bool:
    normalized = str(item_type or "").strip().lower().replace("-", "_")
    return normalized in {"agent_message", "agentmessage"}


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


def is_workspace_console_task(task) -> bool:
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
    if getattr(task, "parent_task_id", None) is not None:
        return False
    return True


@dataclass
class ProcessEntry:
    proc: subprocess.Popen
    output_thread: threading.Thread | None
    alive: bool
    session_id: str
    executor: str
    cwd: str
    resume_session_id: str | None
    resume_message_id: str | None = None
    pending_waiters: list = field(default_factory=list)
    result_text: str | None = None
    had_error: bool = False
    help_requested: bool = False

    @property
    def workspace_id(self) -> str:
        return self.session_id


@dataclass
class AsyncProcessEntry:
    """Async-compatible process entry for asyncio-based subprocess management."""
    proc: asyncio.subprocess.Process
    output_task: asyncio.Task | None
    alive: bool
    session_id: str
    executor: str
    cwd: str
    resume_session_id: str | None
    task_id: str | None = None
    resume_message_id: str | None = None
    pending_waiters: list = field(default_factory=list)
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
    emitted_tool_use_ids: set = field(default_factory=set)
    emitted_tool_result_ids: set = field(default_factory=set)
    # Codex item tracking: maps item.id to a started_at timestamp so we can
    # compute durationMs on completion.
    tool_item_started_at: dict = field(default_factory=dict)
    # Idle-timeout bookkeeping: monotonic timestamp of the most recent stdout
    # line / IPC event we received from the subprocess. The Codex runtime
    # watches this and aborts a task when nothing has streamed for too long
    # (default 180s) — the long total-turn timeout alone isn't enough to
    # catch a hung tool-result loop.
    last_event_at: float = 0.0
    idle_timed_out: bool = False
    idle_timeout_seconds: int | None = None
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
    # Token usage accumulation: tracks input/output/cache tokens seen in stream events
    usage_input: int = 0
    usage_output: int = 0
    usage_cache: int = 0
    cli_cost_usd: float | None = None
    seen_usage_msg_ids: set = field(default_factory=set)

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
        "（模型未按对话格式回复，输出了结构化 JSON。已忽略原文以免覆盖产物。"
        "可重试或切换为更擅长对话的模型。）"
    )


class BaseProcessRuntime:
    def __init__(self, codex_store, log_store, data_dir=None, event_bus=None, processes=None, help_orchestrator=None, refresh_task_result=None):
        self.codex_store = codex_store
        self.log_store = log_store
        self._data_dir = data_dir or "/tmp"
        self._event_bus = event_bus
        self._processes = processes if processes is not None else {}
        self.help_orchestrator = help_orchestrator
        self.refresh_task_result = refresh_task_result

    def _resolve_workspace_id(self, workspace_id: str | None = None, **legacy_kwargs) -> str:
        resolved_workspace_id = workspace_id or legacy_kwargs.pop("session_id", None)
        if legacy_kwargs:
            unexpected = ", ".join(sorted(legacy_kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")
        if not resolved_workspace_id:
            raise TypeError("workspace_id is required")
        return resolved_workspace_id

    async def launch(self, workspace_id: str | None = None, **legacy_kwargs):
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

    async def terminate(self, workspace_id: str | None = None, **legacy_kwargs):
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
            if task is None or task.status in {"done", "failed", "cancelled"}:
                continue
            task.status = "failed"
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)
            execution_process_id = getattr(task, "last_execution_process_id", None)
            if execution_process_id:
                try:
                    await self.codex_store.update_execution_process_status(
                        execution_process_id,
                        "Killed",
                        exit_code=None,
                        completed_at=datetime.now(),
                    )
                except Exception:
                    pass
            if self._event_bus is not None:
                try:
                    await self._event_bus.append({
                        "type": "task_status",
                        "task_id": task_id,
                        "issue_id": task.issue_id,
                        "session_id": task.session_id,
                        "status": "failed",
                        "result": task.result,
                        "execution_process_id": execution_process_id,
                    })
                except Exception:
                    pass

        workspace = await self.codex_store.load_codex_workspace(workspace_id)
        if workspace is not None:
            workspace.status = "idle"
            workspace.last_active_at = datetime.now()
            await self.codex_store.save_codex_workspace(workspace)
        return workspace

    async def terminate_task(self, task_id: str):
        """Kill a specific task process."""
        for process_key, entry in list(self._processes.items()):
            # Check if this entry belongs to the target task
            is_match = (process_key == task_id)
            if hasattr(entry, 'task_id') and entry.task_id == task_id:
                is_match = True

            if is_match and self._owns_entry(entry):
                self._processes.pop(process_key, None)
                await self._cleanup_entry(process_key, entry)

        # Update task + execution-process status in DB. Previously this only
        # updated `task.status`, leaving the execution_process row at
        # "running" — the UI's run/status badge is derived from the EP so it
        # kept showing "Running" even though the task was killed.
        task = await self.codex_store.load_codex_task(task_id)
        if task:
            task.status = "failed"
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)

            execution_process_id = getattr(task, "last_execution_process_id", None)
            if execution_process_id:
                try:
                    await self.codex_store.update_execution_process_status(
                        execution_process_id,
                        "Killed",
                        exit_code=None,
                        completed_at=datetime.now(),
                    )
                except Exception:
                    pass

            if self._event_bus:
                await self._event_bus.append({
                    "type": "task_status",
                    "task_id": task_id,
                    "issue_id": task.issue_id,
                    "session_id": task.session_id,
                    "status": "failed",
                    "result": task.result,
                    "execution_process_id": execution_process_id,
                })

    async def terminate_all(self):
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
                pass
        return terminated

    def _owns_entry(self, entry) -> bool:
        raise NotImplementedError

    def _get_log_path(self, workspace_id: str) -> str:
        return f"{self._data_dir}/codex_session_{workspace_id}.log"

    async def _emit_message_delta(self, workspace_id: str, task_id: str | None, seq: int, delta_text: str):
        """Resolve the task's current execution_process_id and broadcast a message_delta event.

        Skips silently if no event_bus or no resolvable execution_process_id."""
        if self._event_bus is None or not task_id:
            return
        try:
            task = await self.codex_store.load_codex_task(task_id)
        except Exception:
            task = None
        execution_process_id = getattr(task, "last_execution_process_id", None) if task else None
        if not execution_process_id:
            return
        await self._event_bus.append({
            "type": "message_delta",
            "execution_process_id": execution_process_id,
            "task_id": task_id,
            "session_id": workspace_id,
            "seq": seq,
            "delta_text": delta_text,
        })

    async def _append_log(self, workspace_id: str, stream: str, content: str, task_id: str | None):
        execution_process_id = None
        if task_id:
            task = await self.codex_store.load_codex_task(task_id)
            execution_process_id = task.last_execution_process_id if task else None
        
        event = LogEvent(
            id=f"log-{workspace_id}-{datetime.now().timestamp()}",
            session_id=workspace_id,
            stream=stream,
            content=content,
            task_id=task_id,
            execution_process_id=execution_process_id,
            created_at=datetime.now(),
        )
        
        if self._event_bus is not None:
            await self._event_bus.queue_log_event(event)
            await self._event_bus.append({
                "type": "log",
                "id": event.id,
                "session_id": workspace_id,
                "workspace_id": workspace_id,
                "stream": stream,
                "content": content,
                "task_id": task_id,
                "execution_process_id": execution_process_id,
                "created_at": event.created_at.isoformat(),
            })
        else:
            await self.log_store.append_log_event(event)

        try:
            from app.interfaces.codex_ws import stream_manager
            stream_manager.buffer_pending(workspace_id, {
                "id": event.id,
                "stream": stream,
                "content": content,
                "created_at": event.created_at.isoformat(),
            })
        except Exception:
            pass

    async def _log_help_request_outcome(self, workspace_id: str, task_id: str | None, outcome: str, detail: str):
        message = f"request_help {outcome}: {detail}"
        print(f"[HELP] {message}", file=sys.stderr, flush=True)
        await self._append_log(workspace_id, "help_request", message, task_id)

    async def _list_task_messages(self, task_id: str, execution_process_id: str | None = None):
        if execution_process_id:
            try:
                return await self.codex_store.list_codex_task_messages(
                    task_id,
                    execution_process_id=execution_process_id,
                )
            except TypeError:
                pass
        return await self.codex_store.list_codex_task_messages(task_id)

    async def _capture_on_reader(self, workspace_id: str, line: str, entry, task_id: str | None):
        parsed = self._try_parse_json(line)
        if parsed is None:
            return

        if task_id and self.help_orchestrator is not None:
            from app.application.help_event_parser import parse_help_request_event

            help_event = parse_help_request_event(parsed, executor=entry.executor)
            if help_event is not None:
                task = await self.codex_store.load_codex_task(task_id)
                if task is not None and task.status not in {"running", "responding"}:
                    await self._log_help_request_outcome(
                        workspace_id,
                        task_id,
                        "rejected",
                        f"task status is {task.status}",
                    )
                    help_event = None

            if help_event is not None:
                try:
                    self.help_orchestrator.request_help_from_runtime(
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

        # Log every LLM token stream event in real-time and accumulate usage
        if msg_type == "stream_event":
            evt = parsed.get("event", {})
            delta = evt.get("delta", {})
            dt = delta.get("type", "")
            import logging as _lstream
            _lstream.getLogger(__name__).info(
                "[LLM token] task=%s delta_type=%s chars=%d preview=%s",
                task_id, dt, len(delta.get("text", "") or delta.get("thinking", "") or ""),
                (delta.get("text", "") or delta.get("thinking", "") or "")[:100],
            )
            # Feed the stall watchdog: any token (even empty-delta keep-alives)
            # counts as live progress and resets the silence timer.
            from app.application import task_activity
            task_activity.touch(task_id)
            # Accumulate usage from stream_event
            from app.application.usage_utils import extract_usage, extract_message_id
            usage = extract_usage(parsed)
            if usage:
                msg_id = extract_message_id(parsed)
                if msg_id and msg_id not in entry.seen_usage_msg_ids:
                    entry.seen_usage_msg_ids.add(msg_id)
                    entry.usage_input += usage.get("input_tokens", 0) or 0
                    entry.usage_output += usage.get("output_tokens", 0) or 0
                    entry.usage_cache += usage.get("cache_read_input_tokens", 0) or 0

        session_id_val = parsed.get("session_id")
        if session_id_val and entry.resume_session_id is None:
            entry.resume_session_id = session_id_val
            # The per-workspace thread pointer is only for the human console chat.
            # Role/help tasks keep their session on the task alone (per-task
            # identity), so they never pollute the shared pointer.
            task = await self.codex_store.load_codex_task(task_id) if task_id else None
            if task is None or is_workspace_console_task(task):
                workspace = await self.codex_store.load_codex_workspace(workspace_id)
                if workspace:
                    if entry.executor == "codex":
                        workspace.thread_id = session_id_val
                    elif entry.executor == "claude":
                        workspace.claude_thread_id = session_id_val
                    await self.codex_store.save_codex_workspace(workspace)

        if msg_type == "system":
            return

        if msg_type == "assistant":
            assistant_uuid = parsed.get("uuid")
            if assistant_uuid:
                entry.resume_message_id = assistant_uuid
            # Accumulate usage from assistant message
            from app.application.usage_utils import extract_usage, extract_message_id
            usage = extract_usage(parsed)
            if usage:
                msg_id = extract_message_id(parsed)
                if msg_id and msg_id not in entry.seen_usage_msg_ids:
                    entry.seen_usage_msg_ids.add(msg_id)
                    entry.usage_input += usage.get("input_tokens", 0) or 0
                    entry.usage_output += usage.get("output_tokens", 0) or 0
                    entry.usage_cache += usage.get("cache_read_input_tokens", 0) or 0
            msg = parsed.get("message") or {}
            content = msg.get("content", [])
            if isinstance(content, list):
                text_parts = []
                display_parts = []
                for item in content:
                    if isinstance(item, dict):
                        item_type = item.get("type")
                        if item_type == "text":
                            text = item.get("text", "")
                            if text:
                                text_parts.append(text)
                                display_parts.append(text)
                                entry.last_activity_kind = "text"
                        elif item_type == "thinking":
                            thinking = item.get("thinking", "")
                            if thinking:
                                thinking_payload = json.dumps(
                                    {"text": thinking},
                                    ensure_ascii=False,
                                    default=str,
                                )
                                await self._append_log(workspace_id, "thinking", thinking_payload, task_id)
                                entry.last_activity_kind = "reasoning"
                        elif item_type == "tool_use":
                            tool_use_id = item.get("id") or item.get("tool_use_id") or ""
                            if tool_use_id and tool_use_id in entry.emitted_tool_use_ids:
                                continue
                            if tool_use_id:
                                entry.emitted_tool_use_ids.add(tool_use_id)
                            tool_name_val = item.get("name") or item.get("tool_name") or ""
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
                            await self._append_log(workspace_id, "tool_use", payload, task_id)
                            entry.last_activity_kind = "tool"
                            await self._maybe_emit_worktree_dirty(
                                workspace_id, task_id, entry, tool_name_val,
                            )
                if display_parts:
                    new_display = "".join(display_parts).strip()
                    if new_display and new_display != entry.last_emitted_assistant_text:
                        last = entry.last_emitted_assistant_text
                        if new_display.startswith(last):
                            delta = new_display[len(last):]
                        else:
                            delta = new_display
                        if delta:
                            entry.delta_seq += 1
                            entry.last_emitted_assistant_text = new_display
                            await self._emit_message_delta(workspace_id, task_id, entry.delta_seq, delta)
                            import logging as _ldelta
                            _ldelta.getLogger(__name__).info(
                                "[LLM stream] task=%s seq=%d chars=%d\n%s",
                                task_id, entry.delta_seq, len(delta), delta,
                            )
                if text_parts:
                    entry.result_text = "".join(text_parts).strip()
                    entry.produced_real_turn = True
            return

        if msg_type == "user":
            # Claude stream-json emits tool_result entries inside a "user" turn.
            # Surface them as structured tool_result logs so the UI can fold
            # them onto the matching tool_use card.
            msg = parsed.get("message") or {}
            content = msg.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict) or item.get("type") != "tool_result":
                        continue
                    tool_use_id = item.get("tool_use_id") or item.get("id") or ""
                    if tool_use_id and tool_use_id in entry.emitted_tool_result_ids:
                        continue
                    if tool_use_id:
                        entry.emitted_tool_result_ids.add(tool_use_id)
                    raw_content = item.get("content")
                    if isinstance(raw_content, list):
                        text_chunks = []
                        for piece in raw_content:
                            if isinstance(piece, dict) and isinstance(piece.get("text"), str):
                                text_chunks.append(piece["text"])
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
                    await self._append_log(workspace_id, "tool_result", payload, task_id)
            return

        if msg_type == "tool_use":
            tool_name_val = parsed.get("tool_name") or parsed.get("name") or ""
            tool_use_id_val = parsed.get("tool_use_id") or parsed.get("id") or ""
            tool_input = parsed.get("input") or {}
            input_preview = str(tool_input)[:80]
            logger.info("[tool_use] task=%s tool=%s id=%s input=%s", task_id, tool_name_val, tool_use_id_val[:8], input_preview)
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
            await self._append_log(workspace_id, "tool_use", payload, task_id)
            entry.last_activity_kind = "tool"
            await self._maybe_emit_worktree_dirty(
                workspace_id, task_id, entry, tool_name_val,
            )
            return

        if msg_type == "tool_result":
            tool_result_id = parsed.get("tool_use_id") or parsed.get("id") or ""
            is_error = bool(parsed.get("is_error"))
            logger.info("[tool_result] task=%s id=%s error=%s", task_id, tool_result_id[:8], is_error)
            payload = json.dumps(
                {
                    "kind": "tool_result",
                    "tool_use_id": tool_result_id,
                    "output": parsed.get("result") if isinstance(parsed.get("result"), str) else parsed.get("output", ""),
                    "is_error": is_error,
                },
                ensure_ascii=False,
                default=str,
            )
            await self._append_log(workspace_id, "tool_result", payload, task_id)
            return

        if msg_type == "result":
            _terminal_reason = parsed.get("terminal_reason", "")
            if (
                parsed.get("is_error")
                or parsed.get("subtype") == "error_during_execution"
                or _terminal_reason in {"aborted_streaming", "error", "interrupted"}
            ):
                entry.had_error = True
            # Accumulate usage and capture CLI cost from result
            from app.application.usage_utils import extract_usage, extract_message_id
            usage = extract_usage(parsed)
            if usage:
                msg_id = extract_message_id(parsed)
                if msg_id and msg_id not in entry.seen_usage_msg_ids:
                    entry.seen_usage_msg_ids.add(msg_id)
                    entry.usage_input += usage.get("input_tokens", 0) or 0
                    entry.usage_output += usage.get("output_tokens", 0) or 0
                    entry.usage_cache += usage.get("cache_read_input_tokens", 0) or 0
            # Claude CLI may carry total_cost_usd in the result event
            if parsed.get("total_cost_usd") is not None:
                entry.cli_cost_usd = parsed.get("total_cost_usd")
            result_val = parsed.get("result")
            if isinstance(result_val, str) and result_val.strip():
                if not is_cli_control_payload(result_val):
                    entry.result_text = result_val.strip()
                    entry.produced_real_turn = True
            elif isinstance(result_val, dict):
                text = result_val.get("text") or result_val.get("content") or ""
                if text:
                    text_str = text if isinstance(text, str) else str(text)
                    if not is_cli_control_payload(text_str):
                        entry.result_text = text_str
                        entry.produced_real_turn = True
            return

        if msg_type == "item.completed":
            item = parsed.get("item") or {}
            if is_agent_message_item_type(item.get("type")):
                value = item.get("text")
                if isinstance(value, str) and value.strip() and not is_cli_control_payload(value):
                    entry.result_text = value.strip()
                    entry.produced_real_turn = True

    async def _mark_task_done(self, task_id: str, entry):
        if entry.help_requested:
            return
        task = await self.codex_store.load_codex_task(task_id)
        if task:
            execution_process_id = task.last_execution_process_id

            # Branch on EP kind: chat runs must NOT mutate task.result and must
            # NOT trigger artifact persistence. The assistant reply is captured
            # in the message log only.
            is_chat = False
            if execution_process_id and hasattr(self.codex_store, "load_execution_process"):
                try:
                    ep = await self.codex_store.load_execution_process(execution_process_id)
                    is_chat = ep is not None and getattr(ep, "kind", "initial") == "chat"
                except Exception:
                    is_chat = False

            task.status = "done"
            if not is_chat and entry.result_text and not is_unusable_result_text(entry.result_text):
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

            if execution_process_id:
                await self.codex_store.update_execution_process_status(
                    execution_process_id,
                    "Completed",
                    exit_code=0,
                    completed_at=datetime.now(),
                )
                # Persist token usage and cost
                if entry.usage_input or entry.usage_output or entry.cli_cost_usd:
                    from app.application.usage_utils import price_tokens
                    cost = entry.cli_cost_usd if entry.cli_cost_usd is not None else price_tokens(
                        entry.usage_input, entry.usage_output, entry.usage_cache
                    )
                    await self.codex_store.update_execution_process_usage(
                        execution_process_id,
                        input_tokens=entry.usage_input if entry.usage_input else None,
                        output_tokens=entry.usage_output if entry.usage_output else None,
                        cache_read_tokens=entry.usage_cache if entry.usage_cache else None,
                        total_cost_usd=cost if cost > 0 else None,
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

            if self._event_bus is not None:
                await self._event_bus.append({
                    "type": "task_status",
                    "task_id": task_id,
                    "issue_id": task.issue_id,
                    "session_id": task.session_id,
                    "status": task.status,
                    "result": task.result,
                    "review_comment": getattr(task, "review_comment", None),
                    "execution_process_id": execution_process_id,
                })
            
            try:
                from app.interfaces.codex_ws import stream_manager
                stream_manager.buffer_pending(task.session_id, {
                    "type": "task_status",
                    "task_id": task_id,
                    "status": task.status,
                    "review_comment": getattr(task, "review_comment", None),
                })
            except Exception:
                pass

            await self._complete_help_child_if_needed(task, child_status="done", child_result=task.result)

    async def _mark_task_failed(self, task_id: str, entry):
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
            # Persist token usage and cost even on failure
            if entry.usage_input or entry.usage_output or entry.cli_cost_usd:
                from app.application.usage_utils import price_tokens
                cost = entry.cli_cost_usd if entry.cli_cost_usd is not None else price_tokens(
                    entry.usage_input, entry.usage_output, entry.usage_cache
                )
                await self.codex_store.update_execution_process_usage(
                    execution_process_id,
                    input_tokens=entry.usage_input if entry.usage_input else None,
                    output_tokens=entry.usage_output if entry.usage_output else None,
                    cache_read_tokens=entry.usage_cache if entry.usage_cache else None,
                    total_cost_usd=cost if cost > 0 else None,
                )

        if self._event_bus is not None:
            await self._event_bus.append({
                "type": "task_status",
                "task_id": task_id,
                "issue_id": task.issue_id,
                "session_id": task.session_id,
                "status": task.status,
                "result": task.result,
                "execution_process_id": execution_process_id,
            })
        await self._complete_help_child_if_needed(task, child_status="failed", child_result=task.result)

    async def _persist_assistant_message(self, task_id: str, execution_process_id: str | None, content: str | None):
        if not task_id or not execution_process_id or not content:
            return

        from app.domain.models import CodexTaskMessage
        from uuid import uuid4

        text = content.strip()
        if not text:
            return

        existing = await self._list_task_messages(task_id, execution_process_id=execution_process_id)
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
            await self._event_bus.append({
                "type": "message_created",
                "execution_process_id": execution_process_id,
                "message": {
                    "id": message.id,
                    "task_id": message.task_id,
                    "execution_process_id": message.execution_process_id,
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at.isoformat() if message.created_at else None,
                }
            })

    async def _persist_reader_metadata(self, workspace_id: str, task_id: str | None, entry):
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
            workspace.status = "idle"
            workspace.last_active_at = datetime.now()
            await self.codex_store.save_codex_workspace(workspace)

        if task_id and task:
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
                and task.status not in {"done", "failed", "cancelled"}
                and not is_unusable_result_text(entry.result_text)
            ):
                task.result = entry.result_text
            task.updated_at = datetime.now()
            await self.codex_store.save_codex_task(task)

    async def _finalize_task_on_reader_exit(self, task_id: str | None, entry):
        if not task_id or entry.help_requested:
            return

        task = await self.codex_store.load_codex_task(task_id)
        if task is None or task.status in {"done", "failed", "cancelled"}:
            return

        import logging as _log2
        _logger = _log2.getLogger(__name__)

        execution_process_id = task.last_execution_process_id
        exit_code = getattr(entry.proc, "returncode", None)
        if not entry.result_text and not entry.had_error:
            fallback_result = await self._build_idle_timeout_fallback_result(task, entry)
            if fallback_result:
                entry.result_text = fallback_result

        if entry.had_error:
            task.status = "failed"
            process_status = "Failed"
        elif entry.result_text or exit_code == 0:
            task.status = "done"
            if entry.result_text and not is_unusable_result_text(entry.result_text):
                task.result = entry.result_text
            task.updated_at = datetime.now()
            
            # Call refresh_task_result to persist artifacts
            if callable(self.refresh_task_result):
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

            process_status = "Completed" if task.status == "done" else "Failed"
        else:
            task.status = "failed"
            if entry.idle_timed_out:
                timeout_seconds = entry.idle_timeout_seconds or "unknown"
                task.result = (
                    "Runtime went idle before emitting a final result "
                    f"(idle timeout: {timeout_seconds} seconds)."
                )
            process_status = "Failed"

        task.updated_at = datetime.now()
        await self.codex_store.save_codex_task(task)

        if execution_process_id:
            final_exit_code = 0 if task.status == "done" and exit_code is None else exit_code
            await self.codex_store.update_execution_process_status(
                execution_process_id,
                process_status,
                exit_code=final_exit_code,
                completed_at=datetime.now(),
            )
            # Persist token usage and cost
            if entry.usage_input or entry.usage_output or entry.cli_cost_usd:
                from app.application.usage_utils import price_tokens
                cost = entry.cli_cost_usd if entry.cli_cost_usd is not None else price_tokens(
                    entry.usage_input, entry.usage_output, entry.usage_cache
                )
                await self.codex_store.update_execution_process_usage(
                    execution_process_id,
                    input_tokens=entry.usage_input if entry.usage_input else None,
                    output_tokens=entry.usage_output if entry.usage_output else None,
                    cache_read_tokens=entry.usage_cache if entry.usage_cache else None,
                    total_cost_usd=cost if cost > 0 else None,
                )

        if self._event_bus is not None:
            await self._event_bus.append({
                "type": "task_status",
                "task_id": task_id,
                "issue_id": task.issue_id,
                "session_id": task.session_id,
                "status": task.status,
                "result": task.result,
                "execution_process_id": execution_process_id,
            })
        await self._complete_help_child_if_needed(task, child_status=task.status, child_result=task.result)

    async def _complete_help_child_if_needed(self, task, *, child_status: str, child_result: str | None):
        if self.help_orchestrator is None or task is None:
            return
        if task.task_kind != "help_child" or not task.blocked_by_help_id:
            return

        help_request = await self.codex_store.load_help_request(task.blocked_by_help_id)
        if help_request is None or help_request.status in {"completed", "failed", "timed_out", "consumed"}:
            return

        normalized_status = "done" if child_status == "done" else "failed"
        self.help_orchestrator.complete_help_request(
            task.blocked_by_help_id,
            child_status=normalized_status,
            child_result=child_result,
        )

    def _try_parse_json(self, line: str) -> dict | None:
        stripped = line.strip()
        if not stripped.startswith("{"):
            return None
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    async def _build_idle_timeout_fallback_result(self, task, entry) -> str | None:
        """Recover engineer output when the runtime stalls after file changes."""
        if not entry.idle_timed_out or entry.had_error:
            return None
        if getattr(task, "role", None) != "engineer":
            return None
        if not getattr(task, "workspace_path", None):
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

    async def _watchdog(self, workspace_id: str, entry: AsyncProcessEntry, task_id: str | None, timeout_sec: int):
        try:
            await asyncio.sleep(timeout_sec)
            if not entry.alive:
                return
            entry.alive = False
            if entry.proc:
                try:
                    entry.proc.terminate()
                except Exception:
                    pass
            if task_id:
                task = await self.codex_store.load_codex_task(task_id)
                if task and task.status not in {"done", "failed", "cancelled"}:
                    task.status = "failed"
                    task.result = f"Process exceeded maximum timeout of {timeout_sec} seconds"
                    task.updated_at = datetime.now()
                    await self.codex_store.save_codex_task(task)
                    execution_process_id = task.last_execution_process_id
                    if execution_process_id:
                        try:
                            await self.codex_store.update_execution_process_status(
                                execution_process_id,
                                "Failed",
                                exit_code=None,
                                completed_at=datetime.now(),
                            )
                            # Persist token usage and cost even on timeout
                            if entry.usage_input or entry.usage_output or entry.cli_cost_usd:
                                from app.application.usage_utils import price_tokens
                                cost = entry.cli_cost_usd if entry.cli_cost_usd is not None else price_tokens(
                                    entry.usage_input, entry.usage_output, entry.usage_cache
                                )
                                await self.codex_store.update_execution_process_usage(
                                    execution_process_id,
                                    input_tokens=entry.usage_input if entry.usage_input else None,
                                    output_tokens=entry.usage_output if entry.usage_output else None,
                                    cache_read_tokens=entry.usage_cache if entry.usage_cache else None,
                                    total_cost_usd=cost if cost > 0 else None,
                                )
                        except Exception:
                            pass
                    if self._event_bus:
                        await self._event_bus.append({
                            "type": "task_status",
                            "task_id": task_id,
                            "issue_id": task.issue_id,
                            "session_id": task.session_id,
                            "status": "failed",
                            "result": task.result,
                            "execution_process_id": execution_process_id,
                        })
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    # Tool names that mutate the worktree. Matched case-insensitively. Keep
    # tight — we don't want every `Bash` to retrigger diff fetches.
    _WORKTREE_WRITE_TOOLS = frozenset({
        "apply_patch", "edit", "write", "multiedit", "notebookedit",
        "applypatch", "str_replace_editor",
    })

    async def _maybe_emit_worktree_dirty(
        self,
        workspace_id: str,
        task_id: str | None,
        entry: AsyncProcessEntry,
        tool_name: str,
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
            try:
                task = await self.codex_store.load_codex_task(task_id)
                entry.cached_issue_id = getattr(task, "issue_id", None)
            except Exception:
                entry.cached_issue_id = None
        if not entry.cached_issue_id:
            return
        try:
            await self._event_bus.append({
                "type": "worktree_dirty",
                "issue_id": entry.cached_issue_id,
                "session_id": workspace_id,
                "task_id": task_id,
                "tool_name": tool_name,
                "created_at": datetime.now().isoformat(),
            })
        except Exception:
            pass

    async def _heartbeat_loop(self, workspace_id: str, entry: AsyncProcessEntry, task_id: str | None):
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
                task = await self.codex_store.load_codex_task(task_id)
            except Exception:
                task = None
            execution_process_id = getattr(task, "last_execution_process_id", None) if task else None
            if not execution_process_id:
                continue
            now = _time.monotonic()
            last = entry.last_event_at or now
            elapsed_ms = max(0, int((now - last) * 1000))
            try:
                await self._event_bus.append({
                    "type": "heartbeat",
                    "execution_process_id": execution_process_id,
                    "task_id": task_id,
                    "session_id": workspace_id,
                    "phase": entry.last_activity_kind or "idle",
                    "last_event_at": entry.last_event_at,
                    "elapsed_since_last_ms": elapsed_ms,
                    "created_at": datetime.now().isoformat(),
                })
            except Exception:
                pass

    async def _reader_loop(self, workspace_id: str, entry: AsyncProcessEntry, task_id: str | None):
        """Async reader loop using await stdout.readline()."""
        import time as _time
        idle_timeout = int(os.getenv("PROCESS_IDLE_TIMEOUT", "180"))
        max_timeout = int(os.getenv("PROCESS_MAX_TIMEOUT", "1800"))
        entry.last_event_at = _time.monotonic()
        watchdog_task = asyncio.create_task(self._watchdog(workspace_id, entry, task_id, max_timeout))
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(workspace_id, entry, task_id))

        try:
            while entry.alive:
                try:
                    line = await asyncio.wait_for(entry.proc.stdout.readline(), timeout=idle_timeout)
                except asyncio.TimeoutError:
                    entry.idle_timed_out = True
                    entry.idle_timeout_seconds = idle_timeout
                    break
                except asyncio.LimitOverrunError as exc:
                    # A single stdout line exceeded the StreamReader buffer limit.
                    # Don't silently orphan the process — record the error and let
                    # the finally block reap it + finalize the task as failed.
                    entry.had_error = True
                    try:
                        await self._append_log(
                            workspace_id,
                            "stderr",
                            f"stdout line exceeded buffer limit: {exc}",
                            task_id,
                        )
                    except Exception:
                        pass
                    break
                except Exception:
                    break
                if not line:
                    break

                entry.last_event_at = _time.monotonic()
                decoded = line.decode("utf-8", errors="replace")
                await self._append_log(workspace_id, "stdout", decoded, task_id)
                await self._capture_on_reader(workspace_id, decoded, entry, task_id)

                parsed = self._try_parse_json(decoded)
                if parsed and parsed.get("type") in ("turn.completed", "result"):
                    for waiter in list(entry.pending_waiters):
                        waiter.set()
                    entry.pending_waiters.clear()
                    if task_id:
                        if parsed.get("type") == "result" and (parsed.get("is_error") or entry.had_error):
                            # Hard aborts (aborted_streaming, error_during_execution) mean
                            # the stream was cut off mid-way — partial result_text is not a
                            # valid artifact, so always fail. For softer is_error (tool call
                            # failed but model finished), attempt to persist if content exists.
                            _is_hard_abort = (
                                parsed.get("subtype") == "error_during_execution"
                                or parsed.get("terminal_reason") in {"aborted_streaming", "error", "interrupted"}
                            )
                            if entry.result_text and not _is_hard_abort:
                                await self._mark_task_done(task_id, entry)
                            else:
                                await self._mark_task_failed(task_id, entry)
                        else:
                            await self._mark_task_done(task_id, entry)
        except Exception:
            pass
        finally:
            entry.alive = False
            # Always reap the subprocess when the reader loop exits, for ANY
            # reason (EOF, idle timeout, readline exception, cancellation). A
            # live subprocess whose stdout we've stopped draining would orphan
            # and leak its stdout buffer, and stderr.read() below would block
            # forever waiting for an EOF that never comes.
            try:
                if entry.proc and entry.proc.returncode is None:
                    entry.proc.terminate()
                    try:
                        await asyncio.wait_for(entry.proc.wait(), timeout=2)
                    except Exception:
                        try:
                            entry.proc.kill()
                            await asyncio.wait_for(entry.proc.wait(), timeout=2)
                        except Exception:
                            pass
            except Exception:
                pass
            # Cancel the helper tasks and await them via gather(return_exceptions)
            # so a cancelled child surfaces as a result, not a raised
            # CancelledError. The old `wait_for(shield(task))` dance let a
            # CancelledError (a BaseException, not caught by `except Exception`)
            # escape the finally and skip task finalization entirely.
            watchdog_task.cancel()
            heartbeat_task.cancel()
            try:
                await asyncio.gather(watchdog_task, heartbeat_task, return_exceptions=True)
            except asyncio.CancelledError:
                pass

            # Bounded so a still-draining / un-reaped process can't deadlock the
            # finally. The process was reaped above, so EOF should be immediate.
            try:
                stderr = await asyncio.wait_for(entry.proc.stderr.read(), timeout=2)
                if stderr:
                    await self._append_log(workspace_id, "stderr", stderr.decode("utf-8", errors="replace"), task_id)
            except Exception:
                pass

            for waiter in entry.pending_waiters:
                waiter.set()
            entry.pending_waiters.clear()

            await self._persist_reader_metadata(workspace_id, task_id, entry)
            await self._finalize_task_on_reader_exit(task_id, entry)

    async def _cleanup_entry(self, workspace_id: str, entry):
        """Clean up a process entry (sync or async)."""
        try:
            entry.alive = False
            if hasattr(entry, 'proc'):
                if isinstance(entry.proc, asyncio.subprocess.Process):
                    if entry.proc.stdin:
                        entry.proc.stdin.close()
                        try:
                            await entry.proc.stdin.wait_closed()
                        except Exception:
                            pass
                    try:
                        entry.proc.terminate()
                        await asyncio.wait_for(entry.proc.wait(), timeout=2)
                    except (asyncio.TimeoutError, Exception):
                        try:
                            entry.proc.kill()
                            await entry.proc.wait()
                        except Exception:
                            pass
                elif isinstance(entry.proc, subprocess.Popen):
                    try:
                        entry.proc.terminate()
                        entry.proc.wait(timeout=2)
                    except Exception:
                        try:
                            entry.proc.kill()
                        except Exception:
                            pass
        except Exception:
            pass
            
        if hasattr(entry, 'output_task') and entry.output_task and not entry.output_task.done():
            entry.output_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(entry.output_task), timeout=1)
            except Exception:
                pass
