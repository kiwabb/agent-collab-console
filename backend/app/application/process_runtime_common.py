import asyncio
import json
import sys
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.models import LogEvent


def is_agent_message_item_type(item_type: str | None) -> bool:
    normalized = str(item_type or "").strip().lower().replace("-", "_")
    return normalized in {"agent_message", "agentmessage"}


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
    # Token-streaming state: text we last broadcasted to clients via message_delta.
    # On each new assistant partial, emit (new_text - last_emitted_assistant_text)
    # as a delta event. `delta_seq` is monotonically increasing per-entry.
    last_emitted_assistant_text: str = ""
    delta_seq: int = 0

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
        for process_key, entry in list(self._processes.items()):
            if not self._owns_entry(entry):
                continue
            if process_key != workspace_id and entry.workspace_id != workspace_id:
                continue
            self._processes.pop(process_key, None)
            await self._cleanup_entry(process_key, entry)

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
                
        # Update task status in DB
        task = await self.codex_store.load_codex_task(task_id)
        if task:
            task.status = "failed"
            await self.codex_store.save_codex_task(task)
            
            if self._event_bus:
                await self._event_bus.append({
                    "type": "task_status",
                    "task_id": task_id,
                    "session_id": task.session_id,
                    "status": "failed",
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

        session_id_val = parsed.get("session_id")
        if session_id_val and entry.resume_session_id is None:
            entry.resume_session_id = session_id_val
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
            msg = parsed.get("message") or {}
            content = msg.get("content", [])
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        item_type = item.get("type")
                        if item_type == "text":
                            text = item.get("text", "")
                            if text:
                                parts.append(text)
                        elif item_type == "thinking":
                            thinking = item.get("thinking", "")
                            if thinking:
                                parts.append(f"[Thinking: {thinking[:100]}...]" if len(thinking) > 100 else f"[Thinking: {thinking}]")
                if parts:
                    new_text = "".join(parts).strip()
                    # Compute token-level increment vs last broadcast and emit
                    # a message_delta event so the frontend can render typewriter.
                    if new_text and new_text != entry.last_emitted_assistant_text:
                        last = entry.last_emitted_assistant_text
                        if new_text.startswith(last):
                            delta = new_text[len(last):]
                        else:
                            # Non-prefix change (rare revision) — emit full new text as delta.
                            delta = new_text
                        if delta:
                            entry.delta_seq += 1
                            entry.last_emitted_assistant_text = new_text
                            await self._emit_message_delta(workspace_id, task_id, entry.delta_seq, delta)
                    entry.result_text = new_text
            return

        if msg_type == "tool_use":
            tool_name = parsed.get("tool_name") or ""
            tool_data = parsed.get("input", {})
            await self._append_log(workspace_id, "tool_use", f"Tool: {tool_name} | Input: {tool_data}", task_id)
            return

        if msg_type == "tool_result":
            result_content = parsed.get("result", "")
            is_error = parsed.get("is_error", False)
            await self._append_log(workspace_id, "tool_result", f"Result: {result_content} | Error: {is_error}", task_id)
            return

        if msg_type == "result":
            if parsed.get("is_error"):
                entry.had_error = True
            result_val = parsed.get("result")
            if isinstance(result_val, str) and result_val.strip():
                entry.result_text = result_val.strip()
            elif isinstance(result_val, dict):
                text = result_val.get("text") or result_val.get("content") or ""
                if text:
                    entry.result_text = text if isinstance(text, str) else str(text)
            return

        if msg_type == "item.completed":
            item = parsed.get("item") or {}
            if is_agent_message_item_type(item.get("type")):
                value = item.get("text")
                if isinstance(value, str) and value.strip():
                    entry.result_text = value.strip()

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
            if not is_chat and entry.result_text:
                task.result = entry.result_text
            task.updated_at = datetime.now()

            if not is_chat and callable(self.refresh_task_result):
                try:
                    await self.refresh_task_result(task)
                except Exception as exc:
                    entry.had_error = True
                    entry.result_text = str(exc)
                    await self._append_log(task.session_id, "error", str(exc), task_id)
                    await self._mark_task_failed(task_id, entry)
                    return

            if execution_process_id:
                await self.codex_store.update_execution_process_status(
                    execution_process_id,
                    "Completed",
                    exit_code=0,
                    completed_at=datetime.now(),
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
        if entry.result_text:
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

        if self._event_bus is not None:
            await self._event_bus.append({
                "type": "task_status",
                "task_id": task_id,
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
        workspace = await self.codex_store.load_codex_workspace(workspace_id)
        if workspace:
            if entry.resume_session_id:
                if entry.executor == "codex":
                    workspace.thread_id = entry.resume_session_id
                elif entry.executor == "claude":
                    workspace.claude_thread_id = entry.resume_session_id
            workspace.status = "idle"
            workspace.last_active_at = datetime.now()
            await self.codex_store.save_codex_workspace(workspace)

        if task_id:
            task = await self.codex_store.load_codex_task(task_id)
            if task:
                if entry.resume_session_id:
                    task.resume_session_id = entry.resume_session_id
                if entry.resume_message_id:
                    task.resume_message_id = entry.resume_message_id
                if entry.result_text:
                    task.result = entry.result_text
                task.updated_at = datetime.now()
                await self.codex_store.save_codex_task(task)

    async def _finalize_task_on_reader_exit(self, task_id: str | None, entry):
        if not task_id or entry.help_requested:
            return

        task = await self.codex_store.load_codex_task(task_id)
        if task is None or task.status in {"done", "failed", "cancelled"}:
            return

        execution_process_id = task.last_execution_process_id
        exit_code = getattr(entry.proc, "returncode", None)

        if entry.had_error:
            task.status = "failed"
            process_status = "Failed"
        elif entry.result_text or exit_code == 0:
            task.status = "done"
            if entry.result_text:
                task.result = entry.result_text
            task.updated_at = datetime.now()
            
            # Call refresh_task_result to persist artifacts
            if callable(self.refresh_task_result):
                try:
                    await self.refresh_task_result(task)
                except Exception as exc:
                    task.status = "failed"
                    await self._append_log(task.session_id, "error", f"Failed to persist artifacts: {exc}", task_id)
            
            process_status = "Completed"
        else:
            task.status = "failed"
            process_status = "Failed"

        task.updated_at = datetime.now()
        await self.codex_store.save_codex_task(task)

        if execution_process_id:
            await self.codex_store.update_execution_process_status(
                execution_process_id,
                process_status,
                exit_code=exit_code,
                completed_at=datetime.now(),
            )

        if self._event_bus is not None:
            await self._event_bus.append({
                "type": "task_status",
                "task_id": task_id,
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

    # --- Async Process Management ---

    async def _reader_loop(self, workspace_id: str, entry: AsyncProcessEntry, task_id: str | None):
        """Async reader loop using await stdout.readline()."""
        try:
            while entry.alive:
                try:
                    line = await entry.proc.stdout.readline()
                except Exception:
                    break
                if not line:
                    break
                
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
                            await self._mark_task_failed(task_id, entry)
                        else:
                            await self._mark_task_done(task_id, entry)
        except Exception:
            pass
        finally:
            entry.alive = False
            try:
                stderr = await entry.proc.stderr.read()
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
