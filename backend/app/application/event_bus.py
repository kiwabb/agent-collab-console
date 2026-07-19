from __future__ import annotations  # noqa: I001

from collections import deque  # noqa: I001, RUF100
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Protocol, cast
import asyncio
import logging
import threading

from app.application import timeouts
from app.application.task_statuses import is_task_terminal_status
from app.domain.models import CodexTask, LogEvent


JsonEvent = dict[str, object]
logger = logging.getLogger(__name__)


class EventLogStore(Protocol):
    def append_log_event(self, event: LogEvent) -> Awaitable[None] | None: ...


class WorkflowTaskRunner(Protocol):
    def start_task_run(self, task: CodexTask) -> Awaitable[object]: ...


class WorkflowTaskRunnerFactory(Protocol):
    def __call__(
        self, refresh_task_result: Callable[[CodexTask], Awaitable[None]]
    ) -> WorkflowTaskRunner: ...


def _event_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _event_object(value: object) -> JsonEvent:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._buffer_size = timeouts.event_bus_buffer_size()
        self.events: deque[JsonEvent] = deque(maxlen=max(1, self._buffer_size))
        self.subscribers: list[asyncio.Queue[JsonEvent]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._event_seq = 0
        self._log_store: EventLogStore | None = None
        self._db_queue: asyncio.Queue[LogEvent | None] = asyncio.Queue()
        self._db_worker_task: asyncio.Task[None] | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        if self._log_store is not None:
            self._db_worker_task = asyncio.create_task(self._db_worker())

    def set_log_store(self, log_store: EventLogStore) -> None:
        self._log_store = log_store
        if self._loop is not None and self._db_worker_task is None:
            self._db_worker_task = asyncio.create_task(self._db_worker())

    async def _db_worker(self) -> None:
        while True:
            event = await self._db_queue.get()
            try:
                if event is None:
                    break
                await self._persist_log_event(event)
            finally:
                self._db_queue.task_done()

    async def _persist_log_event(self, event: LogEvent) -> None:
        store = self._log_store
        if store is None:
            raise RuntimeError("event bus log store is not configured")
        attempt = 0
        while True:
            try:
                result = store.append_log_event(event)
                if isinstance(result, Awaitable):
                    await result
                if attempt:
                    logger.info(
                        "event bus log write recovered: event_id=%s attempts=%d",
                        event.id,
                        attempt + 1,
                    )
                return
            except Exception:
                attempt += 1
                if attempt == 1 or attempt % 10 == 0:
                    logger.warning(
                        "event bus log write failed; retrying: event_id=%s attempt=%d "
                        "queue_depth=%d",
                        event.id,
                        attempt,
                        self._db_queue.qsize(),
                        exc_info=True,
                    )
                await asyncio.sleep(timeouts.event_bus_log_retry_delay_s())

    async def shutdown(self) -> None:
        worker = self._db_worker_task
        if worker is None:
            return
        await self._db_queue.put(None)
        try:
            await worker
        finally:
            self._db_worker_task = None

    async def queue_log_event(self, event: LogEvent) -> None:
        try:
            if self._log_store is not None:
                await self._db_queue.put(event)
        except Exception:
            logger.exception("event bus log enqueue failed")

    async def append(self, event: Mapping[str, object]) -> None:
        envelope = self._wrap_event(event)
        self.events.append(envelope)

        # Mirror the generic event into the unified audit_log. This is the
        # high-frequency choke point, so it is the one that exercises the
        # bounded-queue drop policy under load. Best-effort + fire-and-forget;
        # conductor_turn/delta + per-line log/delta/heartbeat are skipped (see
        # audit.EVENT_SKIP_TYPES) to avoid a double-write storm.
        self._audit_event(envelope)

        # Broadcast envelopes to global WS subscribers.
        with self._lock:
            for queue in self.subscribers:
                try:
                    queue.put_nowait(envelope)
                except Exception:
                    logger.exception("event bus subscriber enqueue failed")

        # Broadcast to WebSocket managers
        await self._broadcast_to_ws(event, envelope)

    def _audit_event(self, envelope: JsonEvent) -> None:
        """Mirror a generic EventBus event into the unified audit_log.

        Thin forwarding shell over `audit.record_event` — the shaping (skip
        list, payload trim, field extraction) lives in the audit package now.
        Kept as a method so existing tests can call it / drive it via append().
        """
        from app.application import audit

        audit.record_event(envelope)

    async def _broadcast_to_ws(
        self, event: Mapping[str, object], envelope: JsonEvent | None = None
    ) -> None:
        """Broadcast events to WebSocket subscribers via JSON Patch."""
        try:
            from app.interfaces.codex_ws import (  # noqa: E402, E501, RUF100
                message_stream_manager,
                raw_log_stream_manager,
                stream_manager,
            )  # noqa: I001, RUF100

            event_type = event.get("type")
            if event_type == "task_created":
                task = _event_object(event.get("task"))
                workspace_id = _event_str(task.get("session_id"))
                if workspace_id:
                    await stream_manager.add_task(workspace_id, task)
            elif event_type == "task_status":
                task_id = _event_str(event.get("task_id"))
                status = _event_str(event.get("status"))
                result = _event_str(event.get("result"))
                execution_process_id = _event_str(event.get("execution_process_id"))
                workspace_id = _event_str(event.get("session_id")) or _event_str(
                    event.get("workspace_id")
                )
                if workspace_id and task_id and status:
                    await stream_manager.update_task_status(
                        workspace_id,
                        task_id,
                        status,
                        result,
                        execution_process_id=execution_process_id,
                        fallback_event=dict(event),
                    )
                    if execution_process_id and is_task_terminal_status(status):
                        await message_stream_manager.publish_finished(execution_process_id)
                        await raw_log_stream_manager.publish_finished(execution_process_id)

                # Workflow DAG: notify scheduler on terminal task statuses so
                # the graph can advance / open a replan.
                if task_id and status and is_task_terminal_status(status):
                    try:
                        await self._notify_workflow_scheduler(task_id)
                    except Exception:  # noqa: BLE001, RUF100
                        logger.exception(
                            "event bus workflow scheduler notify failed: task_id=%s", task_id
                        )

            elif event_type == "task_deleted":
                task_id = _event_str(event.get("task_id"))
                workspace_id = _event_str(event.get("session_id"))
                if workspace_id and task_id:
                    await stream_manager.remove_task(workspace_id, task_id)
            elif event_type == "message_created":
                message = _event_object(event.get("message"))
                task_id = _event_str(message.get("task_id"))
                execution_process_id = _event_str(event.get("execution_process_id"))
                workspace_id = _event_str(event.get("session_id")) or _event_str(
                    event.get("workspace_id")
                )

                if execution_process_id:
                    await message_stream_manager.publish_message(execution_process_id, message)

                if workspace_id and task_id:
                    await stream_manager.add_message(
                        workspace_id,
                        task_id,
                        message,
                        execution_process_id=execution_process_id,
                    )

            elif event_type == "message_delta":
                # Token-level streaming: broadcast partial assistant text to the
                # per-process message WS subscribers. Frontend reconstructs the
                # in-flight assistant bubble from `seq` + `delta_text`. The final
                # full message arrives later as message_created when the run completes.
                execution_process_id = _event_str(event.get("execution_process_id"))
                if execution_process_id:
                    await message_stream_manager.publish_delta(execution_process_id, dict(event))
                    # Mirror into the raw logs WS so AgentLiveTimeline can render
                    # token flow without subscribing to a second channel. Not
                    # written to the LogEvent table — purely real-time.
                    import datetime as _dt

                    await raw_log_stream_manager.publish_log(
                        execution_process_id,
                        {
                            "kind": "assistant_delta",
                            "seq": event.get("seq"),
                            "delta_text": event.get("delta_text"),
                            "task_id": event.get("task_id"),
                            "session_id": event.get("session_id"),
                            "created_at": _dt.datetime.now().isoformat(),
                        },
                    )

            elif event_type == "heartbeat":
                execution_process_id = _event_str(event.get("execution_process_id"))
                if execution_process_id:
                    await raw_log_stream_manager.publish_log(
                        execution_process_id,
                        {
                            "kind": "heartbeat",
                            "phase": event.get("phase"),
                            "last_event_at": event.get("last_event_at"),
                            "elapsed_since_last_ms": event.get("elapsed_since_last_ms"),
                            "task_id": event.get("task_id"),
                            "session_id": event.get("session_id"),
                            "created_at": event.get("created_at"),
                        },
                    )
            elif event_type == "log":
                task_id = _event_str(event.get("task_id"))
                workspace_id = _event_str(event.get("session_id"))
                execution_process_id = _event_str(event.get("execution_process_id"))
                if workspace_id and task_id:
                    log: JsonEvent = {
                        "id": event.get("id"),
                        "session_id": event.get("session_id"),
                        "stream": event.get("stream"),
                        "content": event.get("content"),
                        "task_id": event.get("task_id"),
                        "execution_process_id": event.get("execution_process_id"),
                        "created_at": event.get("created_at"),
                    }
                    await stream_manager.add_log(
                        workspace_id,
                        task_id,
                        log,
                        execution_process_id=execution_process_id,
                    )
                    if execution_process_id:
                        await raw_log_stream_manager.publish_log(execution_process_id, log)

            elif event_type == "approval_required":
                workspace_id = _event_str(event.get("session_id"))
                execution_process_id = _event_str(event.get("execution_process_id"))
                if workspace_id and execution_process_id:
                    await stream_manager.update_approval(
                        workspace_id,
                        execution_process_id,
                        {
                            "item_id": event.get("item_id"),
                            "method": event.get("method"),
                            "params": event.get("params") or {},
                            "task_id": event.get("task_id"),
                            "session_id": workspace_id,
                            "execution_process_id": execution_process_id,
                        },
                    )

            elif event_type == "approval_resolved":
                workspace_id = _event_str(event.get("session_id"))
                execution_process_id = _event_str(event.get("execution_process_id"))
                if workspace_id and execution_process_id:
                    await stream_manager.update_approval(
                        workspace_id,
                        execution_process_id,
                        None,
                    )

            elif isinstance(event_type, str) and (
                event_type.startswith("issue_")
                or event_type.startswith("session_")
                or event_type.startswith("project_")
                or event_type == "workflow_node_updated"
                or event_type == "worktree_dirty"
                or event_type == "conductor_decision"
                or event_type == "agent_message_posted"
            ):
                # Issue lifecycle + workflow + worktree events flow through the
                # workspace-scoped WS only as BusEvents (no JsonPatch). Consumers
                # subscribe via lastEvent and call their own refetch. session_id
                # is the workspace id used to route the event to the right
                # subscribers.
                workspace_id = _event_str(event.get("session_id")) or _event_str(
                    event.get("workspace_id")
                )
                if workspace_id:
                    await stream_manager.publish_event(workspace_id, dict(event))
        except Exception:
            logger.exception("event bus broadcast failed: event_type=%s", event.get("type"))

    async def _notify_workflow_scheduler(self, task_id: str) -> None:
        """Forward a terminal task_status event to the workflow scheduler."""
        from app.bootstrap import async_store

        if async_store is None:
            return
        task = await async_store.load_codex_task(task_id)
        if task is None or not task.workflow_node_id:
            return
        from app.application.workflow_scheduler import WorkflowScheduler

        scheduler = WorkflowScheduler(
            store=async_store,
            task_dispatcher=_workflow_task_dispatcher,
            event_bus=self,
        )
        await scheduler.on_task_completed(task)

    def subscribe(self) -> asyncio.Queue[JsonEvent]:
        with self._lock:
            queue: asyncio.Queue[JsonEvent] = asyncio.Queue()
            self.subscribers.append(queue)
            return queue

    def unsubscribe(self, queue: asyncio.Queue[JsonEvent]) -> None:
        with self._lock:
            if queue in self.subscribers:
                self.subscribers.remove(queue)

    def replay_from(self, last_event_id: str | None) -> tuple[list[JsonEvent], bool]:
        if not last_event_id:
            return [], False
        replay: list[JsonEvent] = []
        found = False
        for entry in self.events:
            if found:
                replay.append(entry)
                continue
            if entry.get("event_id") == last_event_id:
                found = True
        if found:
            return replay, False
        return [], True

    def _wrap_event(self, event: Mapping[str, object]) -> JsonEvent:
        payload = dict(event)
        event_type = str(payload.pop("type", "unknown"))
        with self._lock:
            self._event_seq += 1
            event_id = f"evt-{self._event_seq:08d}"
        return {
            "v": 1,
            "ts": datetime.now().isoformat(),
            "event_id": event_id,
            "type": event_type,
            "payload": payload,
        }


async def _workflow_task_dispatcher(task: CodexTask) -> None:
    """Dispatch a workflow-scheduler-created task through the real CodexTaskRunner.

    Pulled out as a module-level function so the scheduler can use it from
    both the explicit start_graph path (interfaces/api.py) and the implicit
    settle-after-task-done path (event_bus._notify_workflow_scheduler).
    """
    from app.bootstrap import get_task_runner

    # `refresh_task_result` is None-safe at the runner layer; we don't have a
    # session-level handle here, so pass a noop coroutine. Production callers
    # always provide the real one via bootstrap.
    async def _noop(_t: CodexTask) -> None:
        return None

    runner_factory = cast(WorkflowTaskRunnerFactory, get_task_runner)
    runner = runner_factory(_noop)
    await runner.start_task_run(task)


# Global event bus instance
event_bus = EventBus()
