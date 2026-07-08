from __future__ import annotations  # noqa: I001

import asyncio  # noqa: I001, RUF100
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar, cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.bootstrap import codex_store
from app.application import timeouts
from app.application.task_statuses import is_task_terminal_status
from app.domain.models import CodexTask, CodexTaskMessage, ExecutionProcess, LogEvent
from app.interfaces.execution_process_views import build_execution_process_view


router = APIRouter()
logger = logging.getLogger(__name__)

JsonFrame = dict[str, object]
JsonPatch = list[JsonFrame]
ExecutionProcessViews = dict[str, JsonFrame]
WorkspaceState = dict[str, ExecutionProcessViews]
T = TypeVar("T")


class PendingApprovalManager(Protocol):
    def get_pending_approvals(self) -> dict[str, JsonFrame]: ...


class CodexProcessManagerFactory(Protocol):
    def __call__(self) -> PendingApprovalManager | None: ...


class WsSendChannel(Protocol):
    async def send_json(self, data: object) -> None: ...

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


def _json_frame(value: object) -> JsonFrame:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


# --- Per-subscriber backpressure ------------------------------------------
# A slow / half-open WebSocket must NEVER park the producer coroutine that is
# draining a subprocess's stdout. So producers only ever `try_put` onto a
# bounded per-subscriber queue (synchronous, non-blocking) and a dedicated
# sender task — owned by the endpoint, the socket's SOLE writer — drains that
# queue to the socket. If a queue overflows the subscriber is evicted (closed
# with a non-1000 code) so the client reconnects and re-syncs full state.
WORKSPACE_QUEUE_MAXSIZE = timeouts.ws_workspace_queue_maxsize()
LOG_QUEUE_MAXSIZE = timeouts.ws_log_queue_maxsize()
MESSAGE_QUEUE_MAXSIZE = timeouts.ws_message_queue_maxsize()

_QUEUE_CLOSED = object()  # sentinel: tells the sender task to stop and close
_PONG = object()  # sentinel: tells the sender task to send_text("pong")

class WsSubscriber:
    """One connected client: a raw WebSocket plus a bounded outbound queue.

    Producers call :meth:`try_put` (synchronous, never blocks). The endpoint
    runs :meth:`run_sender` as the socket's only writer. On overflow the
    subscriber self-closes with a non-1000 code so the frontend reconnects and
    re-syncs from a full snapshot.
    """

    __slots__ = ("ws", "queue", "_closed", "evict_code", "evict_reason")  # noqa: RUF023

    def __init__(self, ws: WsSendChannel, maxsize: int) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        self.evict_code = 1011  # non-1000 → frontend treats as non-clean → reconnect
        self.evict_reason = "overflow"

    def try_put(self, frame: object) -> bool:
        """Non-blocking enqueue. Returns False (and evicts) if full/closed."""
        if self._closed:
            return False
        try:
            self.queue.put_nowait(frame)
            return True
        except asyncio.QueueFull:
            self._mark_overflow()
            return False

    def _mark_overflow(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Wake the sender so it stops and closes. Best-effort: if the queue is
        # still full the sender will see _closed is irrelevant — it drains a
        # frame then the next get may be the sentinel; force is not required
        # because the sender closes on ANY sentinel.
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(_QUEUE_CLOSED)

    def close_after_flush(self, code: int = 1000, reason: str = "finished") -> None:
        """Terminal close: drain queued frames, then close with `code`."""
        self.evict_code, self.evict_reason = code, reason
        try:
            self.queue.put_nowait(_QUEUE_CLOSED)
        except asyncio.QueueFull:
            # Saturated already; mark closed so the sender stops after its next
            # drained frame and closes with the code we just set.
            self._closed = True

    async def run_sender(self) -> None:
        """Drain queue → socket until a sentinel. Sole writer of this socket."""
        try:
            while True:
                frame = await self.queue.get()
                if frame is _QUEUE_CLOSED:
                    break
                if frame is _PONG:
                    await self.ws.send_text("pong")
                else:
                    await self.ws.send_json(frame)
                # Overflow eviction may have been signalled while we were draining
                # (and couldn't enqueue the sentinel because the queue was full).
                # Stop after the current frame so the slow client is still closed.
                if self._closed:
                    break
        finally:
            with contextlib.suppress(Exception):
                await self.ws.close(code=self.evict_code, reason=self.evict_reason)


def _fanout(subs: set[WsSubscriber] | None, frame: object) -> None:
    """Non-blocking broadcast: enqueue `frame` to every subscriber; drop any
    that overflow (they self-close and the client reconnects)."""
    if not subs:
        return
    for sub in [s for s in subs if not s.try_put(frame)]:
        subs.discard(sub)


class ExecutionProcessWorkspaceStreamManager:
    """Manages WebSocket subscriptions for workspace-level execution processes."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[WsSubscriber]] = {}
        self._states: dict[str, WorkspaceState] = {}
        self._pending_events: dict[str, list[JsonFrame]] = {}
        self._approval_states: dict[str, JsonFrame] = {}

    def subscribe(self, workspace_id: str, sub: WsSubscriber) -> None:
        self._subscribers.setdefault(workspace_id, set()).add(sub)

    def unsubscribe(self, workspace_id: str, sub: WsSubscriber) -> None:
        subs = self._subscribers.get(workspace_id)
        if subs:
            subs.discard(sub)
            if not subs:
                del self._subscribers[workspace_id]

    def buffer_pending(self, workspace_id: str, event: JsonFrame) -> None:
        self._pending_events.setdefault(workspace_id, []).append(event)

    def consume_pending_events(self, workspace_id: str) -> list[JsonFrame]:
        return self._pending_events.pop(workspace_id, [])

    def restore_pending_events(self, workspace_id: str, events: list[JsonFrame]) -> None:
        if not events:
            return
        self._pending_events[workspace_id] = events + self._pending_events.get(
            workspace_id,
            [],
        )

    async def publish_patch(self, workspace_id: str, patch: JsonPatch) -> None:
        """Publish JSON Patch and any pending events to all subscribers of a workspace."""
        subs = self._subscribers.get(workspace_id)
        if not subs:
            # Keep buffered events intact until a subscriber connects.
            return

        events = self._pending_events.pop(workspace_id, [])
        message = {"JsonPatch": patch}
        if events:
            message["Events"] = events

        _fanout(subs, message)

    async def publish_event(self, workspace_id: str, event: JsonFrame) -> None:
        """Broadcast a single event immediately to all workspace subscribers."""
        subs = self._subscribers.get(workspace_id)
        if not subs:
            self.buffer_pending(workspace_id, event)
            return

        _fanout(subs, {"Events": [event]})

    @staticmethod
    def _serialize_process(
        process: ExecutionProcess,
        task: CodexTask | None,
        messages: list[CodexTaskMessage],
        logs: list[LogEvent],
        pending_approval: JsonFrame | None = None,
    ) -> JsonFrame:
        payload = build_execution_process_view(process, task, messages, logs)
        payload["pending_approval"] = pending_approval
        payload["awaiting_approval"] = pending_approval is not None
        return payload

    @staticmethod
    async def _maybe_await(value: T | Awaitable[T]) -> T:
        if inspect.isawaitable(value):
            return await cast(Awaitable[T], value)
        return value

    async def _load_process_runtime(
        self,
        execution_process_id: str,
    ) -> tuple[ExecutionProcess, CodexTask | None, list[CodexTaskMessage], list[LogEvent]] | None:
        if codex_store is None:
            return None
        process = await self._maybe_await(codex_store.load_execution_process(execution_process_id))
        if process is None:
            return None
        task = await self._maybe_await(codex_store.load_codex_task(process.task_id))
        messages = await self._maybe_await(
            codex_store.list_codex_task_messages(
                process.task_id,
                execution_process_id=process.id,
            )
        )
        logs = await self._maybe_await(
            codex_store.load_log_events(
                process.session_id,
                task_id=process.task_id,
                execution_process_id=process.id,
                limit=1000,
            )
        )
        return process, task, messages, logs

    def _refresh_approval_state_from_runtime(
        self,
        workspace_id: str,
        process_ids: set[str],
    ) -> None:
        try:
            from app.bootstrap import get_codex_process_manager

            manager_factory = cast(CodexProcessManagerFactory, get_codex_process_manager)
            mgr = manager_factory()
            pending = mgr.get_pending_approvals() if mgr is not None else {}
        except Exception:
            pending = {}

        runtime_states = {
            approval["execution_process_id"]: approval
            for approval in pending.values()
            if approval.get("session_id") == workspace_id
            and approval.get("execution_process_id") in process_ids
        }

        for process_id in process_ids:
            if process_id in runtime_states:
                self._approval_states[process_id] = runtime_states[process_id]
            else:
                self._approval_states.pop(process_id, None)

    async def get_state(self, workspace_id: str) -> WorkspaceState:
        processes = (
            await self._maybe_await(codex_store.list_execution_processes(session_id=workspace_id))
            if codex_store
            else []
        )
        process_ids = {process.id for process in processes}
        self._refresh_approval_state_from_runtime(workspace_id, process_ids)
        runtime_rows = (
            await self._maybe_await(codex_store.list_execution_process_runtime_rows(workspace_id))
            if codex_store
            else []
        )
        execution_processes = {
            process.id: self._serialize_process(
                process, task, messages, logs, self._approval_states.get(process.id)
            )
            for process, task, messages, logs in runtime_rows
        }
        self._states[workspace_id] = {"execution_processes": execution_processes}
        return self._states[workspace_id]

    async def _get_process_payload(self, execution_process_id: str) -> tuple[str, JsonFrame] | None:
        runtime_row = await self._load_process_runtime(execution_process_id)
        if runtime_row is None:
            return None
        process, task, messages, logs = runtime_row
        return process.id, self._serialize_process(
            process,
            task,
            messages,
            logs,
            self._approval_states.get(process.id),
        )

    async def _resolve_execution_process_id(
        self, task_id: str | None, execution_process_id: str | None
    ) -> str | None:
        if execution_process_id:
            return execution_process_id
        if codex_store is None or not task_id:
            return None
        task = await self._maybe_await(codex_store.load_codex_task(task_id))
        return task.last_execution_process_id if task else None

    async def _publish_execution_process_view(
        self,
        workspace_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
    ) -> None:
        process_id = await self._resolve_execution_process_id(task_id, execution_process_id)
        if process_id is None:
            return

        result = await self._get_process_payload(process_id)
        if result is None:
            return

        process_id, process_payload = result
        existing_state = self._states.get(workspace_id, {"execution_processes": {}})
        existed = process_id in existing_state["execution_processes"]
        state = await self.get_state(workspace_id)
        patch: JsonPatch = [
            {
                "op": "replace" if existed else "add",
                "path": f"/execution_processes/{process_id}",
                "value": process_payload,
            }
        ]
        state["execution_processes"][process_id] = process_payload
        await self.publish_patch(workspace_id, patch)

    async def publish_execution_process(
        self,
        workspace_id: str,
        execution_process_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        await self._publish_execution_process_view(
            workspace_id,
            task_id=task_id,
            execution_process_id=execution_process_id,
        )

    async def update_task_status(
        self,
        workspace_id: str,
        task_id: str,
        status: str,
        result: str | None = None,
        execution_process_id: str | None = None,
        fallback_event: JsonFrame | None = None,
    ) -> None:
        """Refresh a process view after task status changes and send task_status event."""
        from app.application.task_status_events import build_task_status_event

        # First, publish the task event independently so it cannot be stranded
        # behind an execution-process JsonPatch refresh.
        try:
            task = (
                await self._maybe_await(codex_store.load_codex_task(task_id))
                if codex_store
                else None
            )
        except Exception as exc:
            logger.warning(
                "task_status task load failed; using fallback event: workspace_id=%s task_id=%s error=%s",
                workspace_id,
                task_id,
                exc,
            )
            task = None
        if task:
            effective_status = getattr(task, "status", None) or status
            event = build_task_status_event(
                task,
                status=effective_status,
                result=result if result is not None else getattr(task, "result", None),
                review_comment=getattr(task, "review_comment", None),
                execution_process_id=execution_process_id,
            )
        else:
            event = fallback_event or {
                "type": "task_status",
                "task_id": task_id,
                "project_id": None,
                "issue_id": None,
                "workspace_id": workspace_id,
                "session_id": workspace_id,
                "role": None,
                "task_kind": None,
                "status": status,
                "result": result,
                "review_comment": None,
                "execution_process_id": execution_process_id,
            }
        await self.publish_event(workspace_id, event)
        # Then refresh the execution process view
        try:
            await self.publish_execution_process(
                workspace_id,
                execution_process_id=execution_process_id,
                task_id=task_id,
            )
        except Exception as exc:
            logger.warning(
                "task_status process refresh failed after event delivery: workspace_id=%s task_id=%s error=%s",
                workspace_id,
                task_id,
                exc,
            )

    async def add_task(
        self, workspace_id: str, task: JsonFrame, execution_process_id: str | None = None
    ) -> None:
        """Forward task_created to WS subscribers so the frontend's RunDetail
        can react to new tasks (e.g. workflow stage transitions) without
        forcing a page refresh. The event itself doesn't mutate the
        execution-process JsonPatch state, but it carries the new task id
        the frontend needs to start filtering for the engineer's process.
        """
        await self.publish_event(workspace_id, {"type": "task_created", "task": task})

    async def remove_task(self, workspace_id: str, task_id: str) -> None:
        """Remove any process views associated with a deleted task."""
        state = await self.get_state(workspace_id)
        process_ids = [
            process_id
            for process_id, process_view in state["execution_processes"].items()
            if process_view.get("task_id") == task_id
        ]
        for process_id in process_ids:
            del state["execution_processes"][process_id]
            patch: JsonPatch = [
                {
                    "op": "remove",
                    "path": f"/execution_processes/{process_id}",
                }
            ]
            await self.publish_patch(
                workspace_id,
                patch,
            )

    async def add_message(
        self,
        workspace_id: str,
        task_id: str,
        message: JsonFrame,
        execution_process_id: str | None = None,
    ) -> None:
        await self.publish_execution_process(
            workspace_id,
            execution_process_id=execution_process_id,
            task_id=task_id,
        )

    async def add_log(
        self,
        workspace_id: str,
        task_id: str,
        log: JsonFrame,
        execution_process_id: str | None = None,
    ) -> None:
        await self.publish_execution_process(
            workspace_id,
            execution_process_id=execution_process_id,
            task_id=task_id,
        )

    async def update_approval(
        self,
        workspace_id: str,
        execution_process_id: str,
        approval: JsonFrame | None,
    ) -> None:
        if approval is None:
            self._approval_states.pop(execution_process_id, None)
        else:
            self._approval_states[execution_process_id] = approval
        await self.publish_execution_process(
            workspace_id,
            execution_process_id=execution_process_id,
        )


ExecutionProcessStreamManager = ExecutionProcessWorkspaceStreamManager
workspace_stream_manager = ExecutionProcessWorkspaceStreamManager()
stream_manager = workspace_stream_manager


class ExecutionProcessLogStreamManager:
    """Manages raw log WebSocket subscriptions for a single execution process."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[WsSubscriber]] = {}

    def subscribe(self, process_id: str, sub: WsSubscriber) -> None:
        self._subscribers.setdefault(process_id, set()).add(sub)

    def unsubscribe(self, process_id: str, sub: WsSubscriber) -> None:
        subs = self._subscribers.get(process_id)
        if subs:
            subs.discard(sub)
            if not subs:
                del self._subscribers[process_id]

    async def publish_log(self, process_id: str, log_payload: JsonFrame) -> None:
        _fanout(self._subscribers.get(process_id), log_payload)

    async def publish_finished(self, process_id: str) -> None:
        subs = self._subscribers.pop(process_id, None)
        if not subs:
            return
        # Enqueue the terminal frame, then tell each sender to flush and close
        # cleanly (1000) so the client gets …logs… → {finished:true} → close.
        for sub in list(subs):
            sub.try_put({"finished": True})
            sub.close_after_flush(code=1000, reason="finished")

    async def get_initial_logs(self, process_id: str) -> list[JsonFrame]:
        if codex_store is None:
            return []
        process = await ExecutionProcessWorkspaceStreamManager._maybe_await(
            codex_store.load_execution_process(process_id)
        )
        if process is None:
            return []
        logs = await ExecutionProcessWorkspaceStreamManager._maybe_await(
            codex_store.load_log_events(
                process.session_id,
                task_id=process.task_id,
                execution_process_id=process.id,
                limit=10000,
            )
        )
        return [_json_frame(log.model_dump(mode="json")) for log in logs]


raw_log_stream_manager = ExecutionProcessLogStreamManager()


class ExecutionProcessMessageStreamManager:
    """Manages task message WebSocket subscriptions for a single execution process."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[WsSubscriber]] = {}

    def subscribe(self, process_id: str, sub: WsSubscriber) -> None:
        self._subscribers.setdefault(process_id, set()).add(sub)

    def unsubscribe(self, process_id: str, sub: WsSubscriber) -> None:
        subs = self._subscribers.get(process_id)
        if subs:
            subs.discard(sub)
            if not subs:
                del self._subscribers[process_id]

    async def publish_message(self, process_id: str, message_payload: JsonFrame) -> None:
        _fanout(self._subscribers.get(process_id), message_payload)

    async def publish_delta(self, process_id: str, delta_payload: JsonFrame) -> None:
        """Broadcast a token-level partial update to subscribers.

        Subscribers receive {"type": "message_delta", seq, delta_text, ...}.
        They distinguish from full messages by the "type" field."""
        _fanout(self._subscribers.get(process_id), {**delta_payload, "type": "message_delta"})

    async def publish_finished(self, process_id: str) -> None:
        subs = self._subscribers.pop(process_id, None)
        if not subs:
            return
        for sub in list(subs):
            sub.try_put({"finished": True})
            sub.close_after_flush(code=1000, reason="finished")

    async def get_initial_messages(self, process_id: str) -> list[JsonFrame]:
        if codex_store is None:
            return []
        process = await ExecutionProcessWorkspaceStreamManager._maybe_await(
            codex_store.load_execution_process(process_id)
        )
        if process is None:
            return []
        messages = await ExecutionProcessWorkspaceStreamManager._maybe_await(
            codex_store.list_codex_task_messages(
                process.task_id,
                execution_process_id=process.id,
            )
        )
        return [_json_frame(message.model_dump(mode="json")) for message in messages]


message_stream_manager = ExecutionProcessMessageStreamManager()


async def _serve_subscriber(
    websocket: WebSocket,
    subscribe: Callable[[], object],
    unsubscribe: Callable[[], object],
    sub: WsSubscriber,
) -> None:
    """Run a subscriber connection: a dedicated sender task drains the queue to
    the socket (sole writer) while a receiver task handles client ping → pong
    (routed through the queue so there is never a second concurrent writer).

    `subscribe`/`unsubscribe` are zero-arg callables already bound to the
    manager + key + this `sub`.
    """
    subscribe()

    async def receiver() -> None:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                sub.try_put(_PONG)

    sender_task = asyncio.create_task(sub.run_sender())
    receiver_task = asyncio.create_task(receiver())
    try:
        await asyncio.gather(sender_task, receiver_task)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("websocket subscriber loop failed", exc_info=True)
    finally:
        for task in (sender_task, receiver_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                await task
        unsubscribe()


async def _send_workspace_initial_snapshot(
    websocket: WsSendChannel,
    state: WorkspaceState,
    pending_events: list[JsonFrame] | None = None,
) -> bool:
    initial_patch: JsonPatch = [
        {
            "op": "replace",
            "path": "/execution_processes",
            "value": state["execution_processes"],
        }
    ]
    try:
        message: JsonFrame = {"JsonPatch": initial_patch}
        if pending_events:
            message["Events"] = pending_events
        await websocket.send_json(message)
        await websocket.send_json({"Ready": True})
    except WebSocketDisconnect:
        return False
    return True


@router.websocket("/workspaces/{workspace_id}/execution_processes/ws")
@router.websocket("/sessions/{workspace_id}/execution_processes/ws")
async def execution_process_workspace_stream(websocket: WebSocket, workspace_id: str) -> None:
    """Stream execution-process workspace state via JSON Patch."""
    if codex_store is None:
        await websocket.close(code=500, reason="Store not available")
        return

    workspace = await ExecutionProcessWorkspaceStreamManager._maybe_await(
        codex_store.load_codex_session(workspace_id)
    )
    if workspace is None:
        await websocket.close(code=404, reason="Workspace not found")
        return

    await websocket.accept()

    sub = WsSubscriber(websocket, maxsize=WORKSPACE_QUEUE_MAXSIZE)
    workspace_stream_manager.subscribe(workspace_id, sub)
    state = await workspace_stream_manager.get_state(workspace_id)
    pending_events = workspace_stream_manager.consume_pending_events(workspace_id)
    if not await _send_workspace_initial_snapshot(websocket, state, pending_events):
        workspace_stream_manager.restore_pending_events(workspace_id, pending_events)
        workspace_stream_manager.unsubscribe(workspace_id, sub)
        return

    await _serve_subscriber(
        websocket,
        lambda: None,
        lambda: workspace_stream_manager.unsubscribe(workspace_id, sub),
        sub,
    )


execution_process_stream = execution_process_workspace_stream


@router.websocket("/execution-processes/{process_id}/logs/ws")
async def execution_process_log_stream(websocket: WebSocket, process_id: str) -> None:
    """Stream raw log events for a single execution process."""
    if codex_store is None:
        await websocket.close(code=500, reason="Store not available")
        return

    process = await ExecutionProcessWorkspaceStreamManager._maybe_await(
        codex_store.load_execution_process(process_id)
    )
    if process is None:
        await websocket.close(code=404, reason="Execution process not found")
        return

    await websocket.accept()

    for log in await raw_log_stream_manager.get_initial_logs(process_id):
        await websocket.send_json(log)

    if is_task_terminal_status(process.status):
        await websocket.send_json({"finished": True})
        await websocket.close(code=1000, reason="finished")
        return

    sub = WsSubscriber(websocket, maxsize=LOG_QUEUE_MAXSIZE)
    await _serve_subscriber(
        websocket,
        lambda: raw_log_stream_manager.subscribe(process_id, sub),
        lambda: raw_log_stream_manager.unsubscribe(process_id, sub),
        sub,
    )


@router.websocket("/execution-processes/{process_id}/messages/ws")
async def execution_process_message_stream(websocket: WebSocket, process_id: str) -> None:
    """Stream task messages for a single execution process."""
    if codex_store is None:
        await websocket.close(code=500, reason="Store not available")
        return

    process = await ExecutionProcessWorkspaceStreamManager._maybe_await(
        codex_store.load_execution_process(process_id)
    )
    if process is None:
        await websocket.close(code=404, reason="Execution process not found")
        return

    await websocket.accept()

    for message in await message_stream_manager.get_initial_messages(process_id):
        await websocket.send_json(message)

    if is_task_terminal_status(process.status):
        await websocket.send_json({"finished": True})
        await websocket.close(code=1000, reason="finished")
        return

    sub = WsSubscriber(websocket, maxsize=MESSAGE_QUEUE_MAXSIZE)
    await _serve_subscriber(
        websocket,
        lambda: message_stream_manager.subscribe(process_id, sub),
        lambda: message_stream_manager.unsubscribe(process_id, sub),
        sub,
    )
