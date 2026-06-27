from __future__ import annotations  # noqa: I001

from collections import deque  # noqa: I001, RUF100
from datetime import datetime
from typing import Any
import asyncio
import os
import threading
import sys


# Event types NOT mirrored into the unified audit_log `event` category, to avoid
# a double-write storm. `conductor_turn` / `conductor_turn_delta` are already
# captured (richer, structured) by the conductor co-located audit writer
# (conductor_main_loop._audit_conductor_turn). The high-frequency, low-value
# real-time-only types (`log`, `message_delta`, `heartbeat`) are deliberately
# not persisted as audit rows — `log` lines already land in `log_events` (the
# PRD says NOT to re-copy per-line stdout/stderr into audit_log), and
# delta/heartbeat are pure streaming signals the PRD explicitly leaves on the
# event channel only.
_AUDIT_EVENT_SKIP_TYPES = frozenset(
    {
        "conductor_turn",
        "conductor_turn_delta",
        "log",
        "message_delta",
        "heartbeat",
    }
)
# Cap how much of a generic event payload we mirror into the audit row. The
# audit_logger truncates to 8000 chars on serialize anyway; this keeps the
# common case small and avoids shipping big nested blobs through the queue.
_AUDIT_EVENT_PAYLOAD_LIMIT = 4000


class EventBus:
    def __init__(self):
        self._buffer_size = int(os.getenv("EVENT_BUS_BUFFER_SIZE", "1000"))
        self.events: deque[dict[str, Any]] = deque(maxlen=max(1, self._buffer_size))
        self.subscribers: list[asyncio.Queue] = []
        self._loop = None
        self._lock = threading.Lock()
        self._event_seq = 0
        self._log_store = None
        self._db_queue: asyncio.Queue = asyncio.Queue()
        self._db_worker_task: asyncio.Task | None = None

    def set_loop(self, loop):
        self._loop = loop
        if self._log_store is not None:
            self._db_worker_task = asyncio.create_task(self._db_worker())

    def set_log_store(self, log_store):
        self._log_store = log_store
        if self._loop is not None and self._db_worker_task is None:
            self._db_worker_task = asyncio.create_task(self._db_worker())

    async def _db_worker(self):
        while True:
            try:
                event = await self._db_queue.get()
                if event is None:
                    break
                if self._log_store is not None:
                    await self._log_store.append_log_event(event)
            except Exception as e:
                print(f"[EventBus] DB worker error: {e}", file=sys.stderr)

    async def queue_log_event(self, event):
        try:
            if self._log_store is not None:
                await self._db_queue.put(event)
        except Exception as e:
            print(f"[EventBus] Error queuing log event: {e}", file=sys.stderr)

    async def append(self, event: dict[str, Any]) -> None:
        envelope = self._wrap_event(event)
        self.events.append(envelope)

        # Mirror the generic event into the unified audit_log (PR2). This is the
        # high-frequency choke point, so it is the one that exercises the
        # bounded-queue drop policy under load. Best-effort + fire-and-forget;
        # conductor_turn/delta + per-line log/delta/heartbeat are skipped (see
        # _AUDIT_EVENT_SKIP_TYPES) to avoid a double-write storm.
        self._audit_event(envelope)

        # Broadcast envelopes to global WS subscribers.
        with self._lock:
            for queue in self.subscribers:
                try:
                    queue.put_nowait(envelope)
                except Exception as e:
                    print(f"[EventBus] Error putting event in queue: {e}", file=sys.stderr)

        # Broadcast to WebSocket managers
        await self._broadcast_to_ws(event, envelope)

    def _audit_event(self, envelope: dict[str, Any]) -> None:
        """Record a generic EventBus event into the unified audit_log.

        Best-effort + non-blocking: any failure here is swallowed so audit
        instrumentation can never perturb event broadcasting (the thing it
        audits). Skips types already captured elsewhere or that are pure
        streaming noise (see _AUDIT_EVENT_SKIP_TYPES). Only the event type plus a
        trimmed payload is recorded — the audit_logger truncates again on
        serialize, so this stays cheap on the hot path.
        """
        try:
            event_type = str(envelope.get("type") or "unknown")
            if event_type in _AUDIT_EVENT_SKIP_TYPES:
                return
            payload = envelope.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            issue_id = payload.get("issue_id")
            task_id = payload.get("task_id")
            conductor_task_id = payload.get("conductor_task_id")
            execution_process_id = payload.get("execution_process_id")
            # Trim before enqueue: keep the type + a bounded payload preview so a
            # large nested blob never travels through the queue in full.
            preview = str(payload)
            if len(preview) > _AUDIT_EVENT_PAYLOAD_LIMIT:
                preview = preview[:_AUDIT_EVENT_PAYLOAD_LIMIT] + "…[trimmed]"
            from app.application.audit_logger import audit_logger

            audit_logger.record(
                "event",
                actor=event_type,
                issue_id=str(issue_id) if issue_id else None,
                task_id=str(task_id) if task_id else None,
                conductor_task_id=str(conductor_task_id) if conductor_task_id else None,
                execution_process_id=str(execution_process_id) if execution_process_id else None,
                payload={
                    "type": event_type,
                    "event_id": envelope.get("event_id"),
                    "ts": envelope.get("ts"),
                    "payload_preview": preview,
                },
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            print(f"[EventBus] audit mirror error: {exc}", file=sys.stderr)

    async def _broadcast_to_ws(self, event: dict[str, Any], envelope: dict[str, Any] | None = None):
        """Broadcast events to WebSocket subscribers via JSON Patch."""
        try:
            from app.interfaces.codex_ws import (  # noqa: E402, E501, RUF100
                message_stream_manager,
                raw_log_stream_manager,
                stream_manager,
            )  # noqa: I001, RUF100

            event_type = event.get("type")
            if event_type == "task_created":
                task = event.get("task", {})
                workspace_id = task.get("session_id")
                if workspace_id:
                    await stream_manager.add_task(workspace_id, task)
            elif event_type == "task_status":
                task_id = event.get("task_id")
                status = event.get("status")
                result = event.get("result")
                execution_process_id = event.get("execution_process_id")
                workspace_id = event.get("session_id") or event.get("workspace_id")
                if workspace_id and task_id:
                    await stream_manager.update_task_status(
                        workspace_id,
                        task_id,
                        status,
                        result,
                        execution_process_id=execution_process_id,
                    )
                    if execution_process_id and str(status or "").lower() in {
                        "done",
                        "completed",
                        "failed",
                        "killed",
                    }:
                        await message_stream_manager.publish_finished(execution_process_id)
                        await raw_log_stream_manager.publish_finished(execution_process_id)

                # Workflow DAG: notify scheduler on terminal task statuses so
                # the graph can advance / open a replan.
                if task_id and str(status or "").lower() in {
                    "done",
                    "failed",
                    "completed",
                    "killed",
                }:
                    try:
                        await self._notify_workflow_scheduler(task_id)
                    except Exception as exc:  # noqa: BLE001, RUF100
                        print(f"[EventBus] workflow scheduler notify error: {exc}", file=sys.stderr)

            elif event_type == "task_deleted":
                task_id = event.get("task_id")
                workspace_id = event.get("session_id")
                if workspace_id and task_id:
                    await stream_manager.remove_task(workspace_id, task_id)
            elif event_type == "message_created":
                message = event.get("message", {})
                task_id = message.get("task_id")
                execution_process_id = event.get("execution_process_id")
                workspace_id = event.get("session_id") or event.get("workspace_id")

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
                execution_process_id = event.get("execution_process_id")
                if execution_process_id:
                    await message_stream_manager.publish_delta(execution_process_id, event)
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
                execution_process_id = event.get("execution_process_id")
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
                task_id = event.get("task_id")
                workspace_id = event.get("session_id")
                execution_process_id = event.get("execution_process_id")
                if workspace_id and task_id:
                    log = {
                        "id": event.get("id"),
                        "stream": event.get("stream"),
                        "content": event.get("content"),
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
                workspace_id = event.get("session_id")
                execution_process_id = event.get("execution_process_id")
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
                workspace_id = event.get("session_id")
                execution_process_id = event.get("execution_process_id")
                if workspace_id and execution_process_id:
                    await stream_manager.update_approval(
                        workspace_id,
                        execution_process_id,
                        None,
                    )

            elif event_type and (
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
                workspace_id = event.get("session_id") or event.get("workspace_id")
                if workspace_id:
                    await stream_manager.publish_event(workspace_id, event)
        except Exception as e:
            import traceback

            print(f"[EventBus] Error broadcasting event {event.get('type')}: {e}", file=sys.stderr)
            traceback.print_exc()

    async def _notify_workflow_scheduler(self, task_id: str) -> None:
        """Forward a terminal task_status event to the workflow scheduler."""
        from app.bootstrap import async_store

        if async_store is None:
            return
        task = await async_store.load_codex_task(task_id)
        if task is None or not getattr(task, "workflow_node_id", None):
            return
        from app.application.workflow_scheduler import WorkflowScheduler

        scheduler = WorkflowScheduler(
            store=async_store,
            task_dispatcher=_workflow_task_dispatcher,
            event_bus=self,
        )
        await scheduler.on_task_completed(task)

    def subscribe(self) -> asyncio.Queue:
        with self._lock:
            queue = asyncio.Queue()
            self.subscribers.append(queue)
            return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self.subscribers:
                self.subscribers.remove(queue)

    def replay_from(self, last_event_id: str | None) -> tuple[list[dict[str, Any]], bool]:
        if not last_event_id:
            return [], False
        replay: list[dict[str, Any]] = []
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

    def _wrap_event(self, event: dict[str, Any]) -> dict[str, Any]:
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


async def _workflow_task_dispatcher(task) -> None:
    """Dispatch a workflow-scheduler-created task through the real CodexTaskRunner.

    Pulled out as a module-level function so the scheduler can use it from
    both the explicit start_graph path (interfaces/api.py) and the implicit
    settle-after-task-done path (event_bus._notify_workflow_scheduler).
    """
    from app.bootstrap import get_task_runner

    # `refresh_task_result` is None-safe at the runner layer; we don't have a
    # session-level handle here, so pass a noop coroutine. Production callers
    # always provide the real one via bootstrap.
    async def _noop(_t):  # noqa: ANN001, RUF100
        return None

    runner = get_task_runner(_noop)
    await runner.start_task_run(task)


# Global event bus instance
event_bus = EventBus()
