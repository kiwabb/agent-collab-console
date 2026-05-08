import inspect

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set

from app.bootstrap import codex_store
from app.interfaces.execution_process_views import build_execution_process_view


router = APIRouter()


class ExecutionProcessWorkspaceStreamManager:
    """Manages WebSocket subscriptions for workspace-level execution processes."""

    def __init__(self):
        self._subscribers: Dict[str, Set[WebSocket]] = {}
        self._states: Dict[str, dict] = {}
        self._pending_events: Dict[str, list[dict]] = {}
        self._approval_states: Dict[str, dict] = {}

    def subscribe(self, workspace_id: str, ws: WebSocket):
        self._subscribers.setdefault(workspace_id, set()).add(ws)

    def unsubscribe(self, workspace_id: str, ws: WebSocket):
        subs = self._subscribers.get(workspace_id)
        if subs:
            subs.discard(ws)
            if not subs:
                del self._subscribers[workspace_id]

    def buffer_pending(self, workspace_id: str, event: dict):
        self._pending_events.setdefault(workspace_id, []).append(event)

    async def publish_patch(self, workspace_id: str, patch: list):
        """Publish JSON Patch and any pending events to all subscribers of a workspace."""
        subs = self._subscribers.get(workspace_id, set())
        if not subs:
            return

        events = self._pending_events.pop(workspace_id, [])
        message = {"JsonPatch": patch}
        if events:
            message["Events"] = events

        dead = set()
        for ws in list(subs):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            subs.discard(ws)
    async def publish_event(self, workspace_id: str, event: dict):
        """Broadcast a single event immediately to all workspace subscribers."""
        subs = self._subscribers.get(workspace_id, set())
        if not subs:
            self.buffer_pending(workspace_id, event)
            return

        message = {"Events": [event]}
        dead = set()
        for ws in list(subs):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            subs.discard(ws)

    @staticmethod
    def _serialize_process(process, task, messages, logs, pending_approval: dict | None = None) -> dict:
        payload = build_execution_process_view(process, task, messages, logs)
        payload["pending_approval"] = pending_approval
        payload["awaiting_approval"] = pending_approval is not None
        return payload

    @staticmethod
    async def _maybe_await(value):
        if inspect.isawaitable(value):
            return await value
        return value

    async def _load_process_runtime(self, execution_process_id: str):
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

    def _refresh_approval_state_from_runtime(self, workspace_id: str, process_ids: set[str]):
        try:
            from app.bootstrap import get_codex_process_manager
            mgr = get_codex_process_manager()
            pending = mgr.get_pending_approvals() if mgr is not None else {}
        except Exception:
            pending = {}

        runtime_states = {
            approval["execution_process_id"]: approval
            for approval in pending.values()
            if approval.get("session_id") == workspace_id and approval.get("execution_process_id") in process_ids
        }

        for process_id in process_ids:
            if process_id in runtime_states:
                self._approval_states[process_id] = runtime_states[process_id]
            else:
                self._approval_states.pop(process_id, None)

    async def get_state(self, workspace_id: str) -> dict:
        processes = await self._maybe_await(codex_store.list_execution_processes(session_id=workspace_id)) if codex_store else []
        process_ids = {process.id for process in processes}
        self._refresh_approval_state_from_runtime(workspace_id, process_ids)
        runtime_rows = await self._maybe_await(codex_store.list_execution_process_runtime_rows(workspace_id)) if codex_store else []
        execution_processes = {
            process.id: self._serialize_process(process, task, messages, logs, self._approval_states.get(process.id))
            for process, task, messages, logs in runtime_rows
        }
        self._states[workspace_id] = {"execution_processes": execution_processes}
        return self._states[workspace_id]

    async def _get_process_payload(self, execution_process_id: str) -> tuple[str, dict] | None:
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

    async def _resolve_execution_process_id(self, task_id: str | None, execution_process_id: str | None) -> str | None:
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
    ):
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
        patch = [{
            "op": "replace" if existed else "add",
            "path": f"/execution_processes/{process_id}",
            "value": process_payload,
        }]
        state["execution_processes"][process_id] = process_payload
        await self.publish_patch(workspace_id, patch)

    async def publish_execution_process(
        self,
        workspace_id: str,
        execution_process_id: str | None = None,
        task_id: str | None = None,
    ):
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
        result: str = None,
        execution_process_id: str | None = None,
    ):
        """Refresh a process view after task status changes and send task_status event."""
        # First, publish the event to notify frontend immediately
        task = await self._maybe_await(codex_store.load_codex_task(task_id)) if codex_store else None
        if task:
            event = {
                "type": "task_status",
                "task_id": task_id,
                "status": task.status,
                "review_comment": getattr(task, "review_comment", None),
            }
            self.buffer_pending(workspace_id, event)
        
        # Then refresh the execution process view
        await self.publish_execution_process(
            workspace_id,
            execution_process_id=execution_process_id,
            task_id=task_id,
        )

    async def add_task(self, workspace_id: str, task: dict, execution_process_id: str | None = None):
        """Task metadata does not directly mutate the execution-process stream."""
        return None

    async def remove_task(self, workspace_id: str, task_id: str):
        """Remove any process views associated with a deleted task."""
        state = await self.get_state(workspace_id)
        process_ids = [
            process_id
            for process_id, process_view in state["execution_processes"].items()
            if process_view.get("task_id") == task_id
        ]
        for process_id in process_ids:
            del state["execution_processes"][process_id]
            await self.publish_patch(workspace_id, [{
                "op": "remove",
                "path": f"/execution_processes/{process_id}",
            }])

    async def add_message(
        self,
        workspace_id: str,
        task_id: str,
        message: dict,
        execution_process_id: str | None = None,
    ):
        await self.publish_execution_process(
            workspace_id,
            execution_process_id=execution_process_id,
            task_id=task_id,
        )

    async def add_log(
        self,
        workspace_id: str,
        task_id: str,
        log: dict,
        execution_process_id: str | None = None,
    ):
        await self.publish_execution_process(
            workspace_id,
            execution_process_id=execution_process_id,
            task_id=task_id,
        )

    async def update_approval(
        self,
        workspace_id: str,
        execution_process_id: str,
        approval: dict | None,
    ):
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

    def __init__(self):
        self._subscribers: Dict[str, Set[WebSocket]] = {}

    def subscribe(self, process_id: str, ws: WebSocket):
        self._subscribers.setdefault(process_id, set()).add(ws)

    def unsubscribe(self, process_id: str, ws: WebSocket):
        subs = self._subscribers.get(process_id)
        if subs:
            subs.discard(ws)
            if not subs:
                del self._subscribers[process_id]

    async def publish_log(self, process_id: str, log_payload: dict):
        subs = self._subscribers.get(process_id, set())
        if not subs:
            return

        dead = set()
        for ws in list(subs):
            try:
                await ws.send_json(log_payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            subs.discard(ws)

    async def publish_finished(self, process_id: str):
        subs = self._subscribers.get(process_id, set())
        if not subs:
            return

        dead = set()
        for ws in list(subs):
            try:
                await ws.send_json({"finished": True})
            except Exception:
                dead.add(ws)
        for ws in dead:
            subs.discard(ws)

    async def get_initial_logs(self, process_id: str) -> list[dict]:
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
        return [log.model_dump(mode="json") for log in logs]


raw_log_stream_manager = ExecutionProcessLogStreamManager()


class ExecutionProcessMessageStreamManager:
    """Manages task message WebSocket subscriptions for a single execution process."""

    def __init__(self):
        self._subscribers: Dict[str, Set[WebSocket]] = {}

    def subscribe(self, process_id: str, ws: WebSocket):
        self._subscribers.setdefault(process_id, set()).add(ws)

    def unsubscribe(self, process_id: str, ws: WebSocket):
        subs = self._subscribers.get(process_id)
        if subs:
            subs.discard(ws)
            if not subs:
                del self._subscribers[process_id]

    async def publish_message(self, process_id: str, message_payload: dict):
        subs = self._subscribers.get(process_id, set())
        if not subs:
            return

        dead = set()
        for ws in list(subs):
            try:
                await ws.send_json(message_payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            subs.discard(ws)

    async def publish_finished(self, process_id: str):
        subs = self._subscribers.get(process_id, set())
        if not subs:
            return

        dead = set()
        for ws in list(subs):
            try:
                await ws.send_json({"finished": True})
            except Exception:
                dead.add(ws)
        for ws in dead:
            subs.discard(ws)

    async def get_initial_messages(self, process_id: str) -> list[dict]:
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
        return [message.model_dump(mode="json") for message in messages]


message_stream_manager = ExecutionProcessMessageStreamManager()


@router.websocket("/workspaces/{workspace_id}/execution_processes/ws")
@router.websocket("/sessions/{workspace_id}/execution_processes/ws")
async def execution_process_workspace_stream(websocket: WebSocket, workspace_id: str):
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

    state = await workspace_stream_manager.get_state(workspace_id)
    initial_patch = [{
        "op": "replace",
        "path": "/execution_processes",
        "value": state["execution_processes"],
    }]
    await websocket.send_json({"JsonPatch": initial_patch})
    await websocket.send_json({"Ready": True})

    workspace_stream_manager.subscribe(workspace_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        workspace_stream_manager.unsubscribe(workspace_id, websocket)


execution_process_stream = execution_process_workspace_stream


@router.websocket("/execution-processes/{process_id}/logs/ws")
async def execution_process_log_stream(websocket: WebSocket, process_id: str):
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

    terminal_statuses = {"completed", "failed", "killed", "done"}
    if str(process.status or "").lower() in terminal_statuses:
        await websocket.send_json({"finished": True})
        await websocket.close(code=1000, reason="finished")
        return

    raw_log_stream_manager.subscribe(process_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        raw_log_stream_manager.unsubscribe(process_id, websocket)


@router.websocket("/execution-processes/{process_id}/messages/ws")
async def execution_process_message_stream(websocket: WebSocket, process_id: str):
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

    terminal_statuses = {"completed", "failed", "killed", "done"}
    if str(process.status or "").lower() in terminal_statuses:
        await websocket.send_json({"finished": True})
        await websocket.close(code=1000, reason="finished")
        return

    message_stream_manager.subscribe(process_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        message_stream_manager.unsubscribe(process_id, websocket)
