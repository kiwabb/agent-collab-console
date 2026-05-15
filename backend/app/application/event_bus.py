from typing import Any
import asyncio
import threading
import sys


class EventBus:
    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self.subscribers: list[asyncio.Queue] = []
        self._loop = None
        self._lock = threading.Lock()
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
        self.events.append(event)
        
        # Broadcast to asyncio queues for SSE/subscribers
        with self._lock:
            for queue in self.subscribers:
                try:
                    queue.put_nowait(event)
                except Exception as e:
                    print(f"[EventBus] Error putting event in queue: {e}", file=sys.stderr)

        # Broadcast to WebSocket managers
        await self._broadcast_to_ws(event)

    async def _broadcast_to_ws(self, event: dict[str, Any]):
        """Broadcast events to WebSocket subscribers via JSON Patch."""
        try:
            from app.interfaces.codex_ws import message_stream_manager, raw_log_stream_manager, stream_manager
            
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
                    if execution_process_id and str(status or "").lower() in {"done", "completed", "failed", "killed"}:
                        await message_stream_manager.publish_finished(execution_process_id)
                        await raw_log_stream_manager.publish_finished(execution_process_id)

                # Workflow DAG: notify scheduler on terminal task statuses so
                # the graph can advance / open a replan.
                if task_id and str(status or "").lower() in {"done", "failed", "completed", "killed"}:
                    try:
                        await self._notify_workflow_scheduler(task_id)
                    except Exception as exc:  # noqa: BLE001
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
        scheduler = WorkflowScheduler(store=async_store, task_dispatcher=_workflow_task_dispatcher)
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
    async def _noop(_t):  # noqa: ANN001
        return None
    runner = get_task_runner(_noop)
    await runner.start_task_run(task)


# Global event bus instance
event_bus = EventBus()
