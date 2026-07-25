"""
Minimal JSON-RPC 2.0 client for Codex app-server mode.

This module provides:
- JsonRpcPeer: Bidirectional JSON-RPC communication over stdin/stdout
- AsyncJsonRpcPeer: Async version of JsonRpcPeer using asyncio
- AppServerClient: High-level client implementing Codex app-server protocol
- Auto-approve for FileChangeRequestApproval and CommandExecutionRequestApproval

Based on the Rust implementation in vibe-kanban/crates/executors/src/executors/codex/
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Awaitable
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol  # noqa: UP035

from app.json_safety import JsonObject, object_dict, string_value

logger = logging.getLogger(__name__)


class SyncJsonRpcWriter(Protocol):
    def write(self, data: bytes) -> object: ...

    def flush(self) -> object: ...


class SyncJsonRpcReader(Protocol):
    def readline(self) -> bytes: ...


class JsonRpcEventBus(Protocol):
    def append(self, event: JsonObject) -> object: ...


async def _append_event(event_bus: JsonRpcEventBus, payload: JsonObject) -> None:
    result = event_bus.append(payload)
    if isinstance(result, Awaitable):
        await result


class PendingResponse:
    """Represents a pending JSON-RPC response."""

    Result = "result"
    Error = "error"
    Shutdown = "shutdown"


@dataclass
class JsonRpcMessage:
    """Represents a parsed JSON-RPC message."""

    type: str  # "request", "response", "error", "notification"
    method: str | None = None
    request_id: object | None = None
    params: JsonObject | None = None
    result: object | None = None
    error: JsonObject | None = None
    raw: str = ""


def _json_rpc_request_payload(
    method: str, params: JsonObject | None = None, request_id: int | None = None
) -> JsonObject:
    payload: JsonObject = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params
    return payload


def _json_rpc_response_payload(request_id: object | None, result: object) -> JsonObject:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def _json_rpc_error_payload(
    request_id: object | None,
    code: int,
    message: str,
    data: object | None = None,
) -> JsonObject:
    error: JsonObject = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    }


def _parse_json_rpc_message(line: str) -> JsonRpcMessage | None:
    """Parse one JSON-RPC line using the same rules for sync and async peers."""
    if not line.startswith("{"):
        return None
    try:
        data: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    if "error" in data and "id" in data:
        return JsonRpcMessage(
            type="error",
            request_id=data.get("id"),
            error=object_dict(data.get("error")),
            raw=line,
        )
    if "id" in data and "result" in data:
        return JsonRpcMessage(
            type="response",
            request_id=data.get("id"),
            result=data.get("result"),
            raw=line,
        )
    if "id" in data and "method" in data:
        return JsonRpcMessage(
            type="request",
            request_id=data.get("id"),
            method=string_value(data.get("method")),
            params=object_dict(data.get("params")),
            raw=line,
        )
    if "method" in data:
        return JsonRpcMessage(
            type="notification",
            method=string_value(data.get("method")),
            params=object_dict(data.get("params")),
            raw=line,
        )
    return None


def _server_request_from_message(msg: JsonRpcMessage) -> ServerRequest:
    method = msg.method or ""
    params = msg.params or {}

    if method == "file_change/request_approval":
        return FileChangeRequestApproval(
            request_id=msg.request_id,
            method=method,
            params=params,
            item_id=string_value(params.get("item_id")),
        )
    if method == "command_execution/request_approval":
        return CommandExecutionRequestApproval(
            request_id=msg.request_id,
            method=method,
            params=params,
            item_id=string_value(params.get("item_id")),
        )
    return ServerRequest(
        request_id=msg.request_id,
        method=method,
        params=params,
    )


@dataclass
class ServerRequest:
    """Base class for server-initiated requests from Codex."""

    request_id: object | None
    method: str
    params: JsonObject


@dataclass
class FileChangeRequestApproval(ServerRequest):
    """File change approval request (codex.apply_patch)."""

    item_id: str = ""


@dataclass
class CommandExecutionRequestApproval(ServerRequest):
    """Command execution approval request (codex.exec_command)."""

    item_id: str = ""


class Decision(str, Enum):  # noqa: UP042
    """Approval decisions for server requests."""

    Accept = "accept"
    AcceptForSession = "acceptForSession"
    Decline = "decline"
    Cancel = "cancel"


@dataclass
class JsonRpcCallbacks:
    """Callbacks for handling JSON-RPC events. Override as needed."""

    on_notification: Callable[[str, JsonObject], object] | None = None  # Returns True to stop reading
    on_server_request: Callable[[ServerRequest], object] | None = None  # Returns response or None
    on_response: Callable[[object | None, object | None], None] | None = None
    on_error: Callable[[object | None, JsonObject], None] | None = None
    on_raw_line: Callable[[str], object] | None = None


class JsonRpcPeer:
    """
    Bidirectional JSON-RPC peer for Codex app-server communication.

    Handles:
    - Sending requests with unique IDs and waiting for responses
    - Receiving and dispatching notifications
    - Handling server-initiated requests (approvals)
    """

    def __init__(
        self,
        stdin: SyncJsonRpcWriter,
        stdout: SyncJsonRpcReader,
        callbacks: JsonRpcCallbacks | None = None,
    ) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._callbacks = callbacks or JsonRpcCallbacks()
        self._pending: dict[object, threading.Event] = {}
        self._pending_results: dict[object, object | None] = {}
        self._pending_errors: dict[object, JsonObject] = {}
        self._id_counter = 0
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._reader_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the reader thread."""
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        """Stop the reader thread and signal shutdown."""
        self._shutdown.set()
        if self._reader_thread:
            self._reader_thread.join(timeout=5)

    def next_request_id(self) -> int:
        """Generate the next unique request ID."""
        with self._lock:
            self._id_counter += 1
            return self._id_counter

    def send(
        self, method: str, params: JsonObject | None = None, request_id: int | None = None
    ) -> bool:
        """Send a JSON-RPC request or notification."""
        try:
            raw = json.dumps(_json_rpc_request_payload(method, params, request_id))
            self._stdin.write(raw.encode("utf-8") + b"\n")
            self._stdin.flush()
            return True
        except (BrokenPipeError, OSError) as e:
            logger.warning("json-rpc send failed: error=%s", e)
            return False

    def request(
        self, method: str, params: JsonObject | None = None, timeout: float = 600
    ) -> object | None:
        """
        Send a JSON-RPC request and wait for response.

        Returns the result on success, raises on error or timeout.
        """
        request_id = self.next_request_id()
        evt = threading.Event()

        with self._lock:
            self._pending[request_id] = evt

        try:
            self.send(method, params, request_id)
            received = evt.wait(timeout=timeout)
            if not received:
                raise TimeoutError(f"Request {method} timed out after {timeout}s")

            # Check for errors first
            if request_id in self._pending_errors:
                error = self._pending_errors.pop(request_id)
                raise Exception(f"JSON-RPC error: {error}")

            return self._pending_results.get(request_id)
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
                self._pending_results.pop(request_id, None)
                self._pending_errors.pop(request_id, None)

    def _reader_loop(self) -> None:
        """Main loop that reads and dispatches JSON-RPC messages."""
        try:
            while not self._shutdown.is_set():
                raw_line = self._stdout.readline()
                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                if self._callbacks.on_raw_line:
                    self._callbacks.on_raw_line(line)

                msg = self._parse_message(line)
                if msg is None:
                    # Non-JSON line - pass to callback
                    if self._callbacks.on_notification:
                        self._callbacks.on_notification(line, {})
                    continue

                if msg.type == "response":
                    self._handle_response(msg)
                elif msg.type == "error":
                    self._handle_error(msg)
                elif msg.type == "request":
                    self._handle_request(msg)
                elif msg.type == "notification":
                    self._handle_notification(msg)

        except Exception:
            logger.exception("json-rpc reader loop failed")
        finally:
            self._shutdown.set()
            # Signal all pending waiters
            with self._lock:
                for evt in self._pending.values():
                    evt.set()

    def _parse_message(self, line: str) -> JsonRpcMessage | None:
        """Parse a JSON-RPC message from a raw line."""
        return _parse_json_rpc_message(line)

    def _handle_response(self, msg: JsonRpcMessage) -> None:
        """Handle an incoming JSON-RPC response."""
        if self._callbacks.on_response:
            self._callbacks.on_response(msg.request_id, msg.result)

        with self._lock:
            if msg.request_id in self._pending:
                self._pending_results[msg.request_id] = msg.result
                self._pending[msg.request_id].set()

    def _handle_error(self, msg: JsonRpcMessage) -> None:
        """Handle an incoming JSON-RPC error response."""
        if self._callbacks.on_error:
            self._callbacks.on_error(msg.request_id, msg.error or {})

        with self._lock:
            if msg.request_id in self._pending:
                self._pending_errors[msg.request_id] = msg.error or {}
                self._pending[msg.request_id].set()

    def _handle_request(self, msg: JsonRpcMessage) -> None:
        """Handle an incoming JSON-RPC request from the server."""
        response = None
        if self._callbacks.on_server_request:
            server_req = self._create_server_request(msg)
            response = self._callbacks.on_server_request(server_req)

        # Send response if callback returned one
        if response is not None and msg.request_id is not None:
            self.send_response(msg.request_id, response)

    def _handle_notification(self, msg: JsonRpcMessage) -> None:
        """Handle an incoming JSON-RPC notification."""
        if self._callbacks.on_notification:
            should_stop = self._callbacks.on_notification(msg.method or "", msg.params or {})
            if should_stop:
                self._shutdown.set()

    def _create_server_request(self, msg: JsonRpcMessage) -> ServerRequest:
        """Create a ServerRequest object from a JSON-RPC request."""
        return _server_request_from_message(msg)

    def send_response(self, request_id: object | None, result: object) -> bool:
        """Send a JSON-RPC response."""
        try:
            raw = json.dumps(_json_rpc_response_payload(request_id, result))
            self._stdin.write(raw.encode("utf-8") + b"\n")
            self._stdin.flush()
            return True
        except (BrokenPipeError, OSError) as e:
            logger.warning("json-rpc send response failed: error=%s", e)
            return False


class AppServerClient:
    """
    High-level client for Codex app-server mode.

    Implements:
    - Initialize handshake
    - Thread start/fork
    - Turn start
    - Manual approval handling for file changes and command executions

    Supports both sync (JsonRpcPeer) and async (AsyncJsonRpcPeer) peers.
    """

    def __init__(
        self,
        codex_store: object,
        log_store: object,
        event_bus: JsonRpcEventBus | None = None,
        notification_callback: Callable[[str, JsonObject], object] | None = None,
        auto_approve: bool = True,
        plan_mode: bool = False,
    ) -> None:
        self._codex_store = codex_store
        self._log_store = log_store
        self._event_bus = event_bus
        self._auto_approve = auto_approve
        self._plan_mode = plan_mode
        self._peer: JsonRpcPeer | AsyncJsonRpcPeer | None = None
        self._thread_id: str | None = None
        self._callbacks: JsonRpcCallbacks | None = None
        self._notification_callback = notification_callback
        # Pending approval requests awaiting user decision (for manual approval mode)
        self._pending_approvals: dict[str, ServerRequest] = {}
        # Callback to invoke when an approval is needed (set by CodexProcessManager)
        self._approval_callback: Callable[[str, ServerRequest], object] | None = None

    def attach_peer(self, peer: JsonRpcPeer | AsyncJsonRpcPeer) -> None:
        """Attach a JsonRpcPeer or AsyncJsonRpcPeer to this client."""
        self._peer = peer
        existing_callbacks = peer._callbacks or JsonRpcCallbacks()
        self._callbacks = self._create_callbacks(existing_callbacks)
        peer._callbacks = self._callbacks

    def _require_peer(self) -> JsonRpcPeer | AsyncJsonRpcPeer:
        if self._peer is None:
            raise RuntimeError("JSON-RPC peer is not attached")
        return self._peer

    def _create_callbacks(
        self, existing_callbacks: JsonRpcCallbacks | None = None
    ) -> JsonRpcCallbacks:
        """Create callbacks for JSON-RPC events."""
        existing_callbacks = existing_callbacks or JsonRpcCallbacks()
        return JsonRpcCallbacks(
            on_notification=self._on_notification,
            on_server_request=self._on_server_request,
            on_response=self._on_response,
            on_error=self._on_error,
            on_raw_line=existing_callbacks.on_raw_line,
        )

    async def initialize(self) -> JsonObject:
        """
        Send initialize request to Codex app-server.

        Returns the InitializeResponse.
        """
        params: JsonObject = {
            "clientInfo": {
                "name": "agent-collab-console",
                "version": "1.0.0",
            },
            "capabilities": {
                "experimentalApi": True,
            },
        }
        peer = self._require_peer()
        if isinstance(peer, AsyncJsonRpcPeer):
            result = await peer.request("initialize", params)
        else:
            result = peer.request("initialize", params)
        return object_dict(result)

    async def initialized(self) -> bool:
        """Send initialized notification."""
        peer = self._require_peer()
        if isinstance(peer, AsyncJsonRpcPeer):
            return await peer.send("initialized")
        else:
            return peer.send("initialized")

    async def thread_start(self, prompt: str | None = None) -> JsonObject:
        """
        Start a new thread.

        Args:
            prompt: Optional initial prompt for the thread

        Returns the ThreadStartResponse with thread_id.
        """
        params: JsonObject = {}
        if prompt:
            params["input"] = [{"type": "text", "text": prompt, "text_elements": []}]

        peer = self._require_peer()
        if isinstance(peer, AsyncJsonRpcPeer):
            result = await peer.request("thread/start", params)
        else:
            result = peer.request("thread/start", params)

        result_obj = object_dict(result)
        thread_id = string_value(result_obj.get("thread_id"))
        thread = object_dict(result_obj.get("thread"))
        if thread_id:
            self._thread_id = thread_id
        elif string_value(thread.get("id")):
            self._thread_id = string_value(thread.get("id"))
        return result_obj

    async def thread_fork(self, thread_id: str) -> JsonObject:
        """
        Fork an existing thread to create a new session.

        Args:
            thread_id: The thread ID to fork from

        Returns the ThreadForkResponse with new thread_id.
        """
        params: JsonObject = {"threadId": thread_id}
        peer = self._require_peer()
        if isinstance(peer, AsyncJsonRpcPeer):
            result = await peer.request("thread/fork", params)
        else:
            result = peer.request("thread/fork", params)

        result_obj = object_dict(result)
        new_thread_id = string_value(result_obj.get("thread_id"))
        thread = object_dict(result_obj.get("thread"))
        if new_thread_id:
            self._thread_id = new_thread_id
        elif string_value(thread.get("id")):
            self._thread_id = string_value(thread.get("id"))
        return result_obj

    async def turn_start(self, prompt: str, thread_id: str | None = None) -> JsonObject:
        """
        Start a turn with user input.

        Args:
            prompt: The user's prompt
            thread_id: Optional thread ID (uses stored if not provided)

        Returns the TurnStartResponse.
        """
        tid = thread_id or self._thread_id
        if not tid:
            raise ValueError("No thread_id available. Call thread_start or thread_fork first.")

        params: JsonObject = {
            "threadId": tid,
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
        }
        peer = self._require_peer()
        if isinstance(peer, AsyncJsonRpcPeer):
            return object_dict(await peer.request("turn/start", params))
        return object_dict(peer.request("turn/start", params))

    async def _on_notification(self, method: str, params: JsonObject) -> bool:
        """
        Handle incoming notifications.

        Returns True to stop the reader loop (e.g., on shutdown).
        """
        logger.debug("[JSON-RPC] Notification: %s %s", method, params)

        # Log all notifications
        if self._event_bus:
            payload: JsonObject = {
                "type": "notification",
                "method": method,
                "params": params,
            }
            await _append_event(self._event_bus, payload)

        if self._notification_callback:
            if asyncio.iscoroutinefunction(self._notification_callback):
                should_stop = await self._notification_callback(method, params)
            else:
                should_stop = self._notification_callback(method, params)
            if should_stop:
                return True

        return False

    async def _on_server_request(self, request: ServerRequest) -> JsonObject | None:
        """
        Handle server-initiated requests (approvals).

        In auto_approve mode (Phase 1): returns decision immediately.
        In manual mode (Phase 2): stores request and emits SSE event, returns None.
        """
        logger.debug("[JSON-RPC] Server request: %s %s", request.method, request.params)

        # Log the approval request
        if self._event_bus:
            payload: JsonObject = {
                "type": "server_request",
                "method": request.method,
                "params": request.params,
            }
            await _append_event(self._event_bus, payload)

        # Auto-approve for Phase 1
        if self._auto_approve:
            if isinstance(request, FileChangeRequestApproval):  # noqa: SIM114
                return {"decision": Decision.AcceptForSession.value}
            elif isinstance(request, CommandExecutionRequestApproval):
                return {"decision": Decision.AcceptForSession.value}

        # Manual approval mode (Phase 2) - store and emit event
        if isinstance(request, (FileChangeRequestApproval, CommandExecutionRequestApproval)):
            item_id = request.item_id or str(request.request_id)
            self._pending_approvals[item_id] = request

            # Invoke callback if set
            if self._approval_callback:
                if asyncio.iscoroutinefunction(self._approval_callback):
                    await self._approval_callback(item_id, request)
                else:
                    self._approval_callback(item_id, request)

            # Return None to indicate we want to wait for resolve_pending_request
            return None

        return None

    def set_approval_callback(self, callback: Callable[[str, ServerRequest], object]) -> None:
        """Set callback to invoke when an approval request is received."""
        self._approval_callback = callback

    async def resolve_pending_request(self, item_id: str, decision: str) -> bool:
        """
        Resolve a pending approval request.

        Args:
            item_id: The item_id of the pending request
            decision: One of "accept", "acceptForSession", "decline", "cancel"

        Returns True if the request was found and resolved.
        """
        request = self._pending_approvals.pop(item_id, None)
        if request is None:
            logger.warning("json-rpc approval missing: item_id=%s", item_id)
            return False

        response: JsonObject = {"decision": decision}
        if self._peer:
            if isinstance(self._peer, AsyncJsonRpcPeer):
                await self._peer.send_response(request.request_id, response)
            else:
                self._peer.send_response(request.request_id, response)
            logger.info("json-rpc approval resolved: item_id=%s decision=%s", item_id, decision)
        return True

    def get_pending_approvals(self) -> dict[str, ServerRequest]:
        """Return all pending approval requests."""
        return self._pending_approvals.copy()

    def _on_response(self, request_id: object | None, result: object | None) -> None:
        """Handle incoming responses."""
        logger.debug("[JSON-RPC] Response %s: %s", request_id, result)

    def _on_error(self, request_id: object | None, error: JsonObject) -> None:
        """Handle incoming error responses."""
        logger.debug("[JSON-RPC] Error %s: %s", request_id, error)


# --- Async JSON-RPC Peer (Phase 2) ---


class AsyncJsonRpcPeer:
    """
    Async version of JsonRpcPeer using asyncio for subprocess communication.

    Provides the same bidirectional JSON-RPC communication but uses:
    - asyncio.Lock instead of threading.Lock
    - asyncio.Event instead of threading.Event
    - asyncio.create_task instead of threading.Thread
    - await stream.readline() instead of blocking readline()
    """

    def __init__(
        self,
        stdin: asyncio.StreamWriter,
        stdout: asyncio.StreamReader,
        callbacks: JsonRpcCallbacks | None = None,
    ) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._callbacks = callbacks or JsonRpcCallbacks()
        self._pending: dict[object, asyncio.Event] = {}
        self._pending_results: dict[object, object | None] = {}
        self._pending_errors: dict[object, JsonObject] = {}
        self._id_counter = 0
        self._lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the async reader task."""
        self._reader_task = asyncio.create_task(self._async_reader_loop())

    async def stop(self) -> None:
        """Stop the reader task and signal shutdown."""
        self._shutdown.set()
        if self._reader_task:
            try:
                await asyncio.wait_for(self._reader_task, timeout=5)
            except asyncio.TimeoutError:  # noqa: UP041
                self._reader_task.cancel()

    async def next_request_id(self) -> int:
        """Generate the next unique request ID."""
        async with self._lock:
            self._id_counter += 1
            return self._id_counter

    async def send(
        self, method: str, params: JsonObject | None = None, request_id: int | None = None
    ) -> bool:
        """Send a JSON-RPC request or notification."""
        try:
            raw = json.dumps(_json_rpc_request_payload(method, params, request_id))
            self._stdin.write(raw.encode("utf-8") + b"\n")
            await self._stdin.drain()
            return True
        except (BrokenPipeError, OSError) as e:
            logger.warning("async json-rpc send failed: error=%s", e)
            return False

    async def request(
        self, method: str, params: JsonObject | None = None, timeout: float = 600
    ) -> object | None:
        """Send a JSON-RPC request and wait for response."""
        request_id = await self.next_request_id()
        evt = asyncio.Event()

        async with self._lock:
            self._pending[request_id] = evt

        try:
            await self.send(method, params, request_id)
            try:
                await asyncio.wait_for(evt.wait(), timeout=timeout)
            except asyncio.TimeoutError:  # noqa: UP041
                raise TimeoutError(f"Request {method} timed out after {timeout}s")  # noqa: B904

            if request_id in self._pending_errors:
                error = self._pending_errors.pop(request_id)
                raise Exception(f"JSON-RPC error: {error}")

            return self._pending_results.get(request_id)
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)
                self._pending_results.pop(request_id, None)
                self._pending_errors.pop(request_id, None)

    async def _async_reader_loop(self) -> None:
        """Async main loop that reads and dispatches JSON-RPC messages."""
        try:
            while not self._shutdown.is_set():
                try:
                    raw_line = await asyncio.wait_for(self._stdout.readline(), timeout=1)
                except asyncio.TimeoutError:  # noqa: UP041
                    continue
                except Exception:
                    break

                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                if self._callbacks.on_raw_line:
                    res = self._callbacks.on_raw_line(line)
                    if asyncio.iscoroutine(res):
                        await res

                msg = self._parse_message(line)
                if msg is None:
                    if self._callbacks.on_notification:
                        res = self._callbacks.on_notification(line, {})
                        if asyncio.iscoroutine(res):
                            await res
                    continue

                if msg.type == "response":
                    await self._handle_response(msg)
                elif msg.type == "error":
                    await self._handle_error(msg)
                elif msg.type == "request":
                    await self._handle_request(msg)
                elif msg.type == "notification":
                    await self._handle_notification(msg)

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("async json-rpc reader loop failed")
        finally:
            self._shutdown.set()
            async with self._lock:
                for evt in self._pending.values():
                    evt.set()

    def _parse_message(self, line: str) -> JsonRpcMessage | None:
        """Parse a JSON-RPC message from a line."""
        return _parse_json_rpc_message(line)

    async def _handle_response(self, msg: JsonRpcMessage) -> None:
        """Handle incoming response."""
        if self._callbacks.on_response:
            self._callbacks.on_response(msg.request_id, msg.result)
        async with self._lock:
            if msg.request_id in self._pending:
                self._pending_results[msg.request_id] = msg.result
                self._pending[msg.request_id].set()

    async def _handle_error(self, msg: JsonRpcMessage) -> None:
        """Handle incoming error response."""
        if self._callbacks.on_error:
            self._callbacks.on_error(msg.request_id, msg.error or {})
        async with self._lock:
            if msg.request_id in self._pending:
                self._pending_errors[msg.request_id] = msg.error or {}
                self._pending[msg.request_id].set()

    async def _handle_request(self, msg: JsonRpcMessage) -> None:
        """Handle incoming request from server."""
        if self._callbacks.on_server_request:
            cb = self._callbacks.on_server_request
            response = cb(_server_request_from_message(msg))
            if isinstance(response, Awaitable):
                response = await response
            if response is not None:
                await self.send_response(msg.request_id, response)

    async def send_response(self, request_id: object | None, result: object) -> bool:
        """Send a JSON-RPC response."""
        try:
            raw = json.dumps(_json_rpc_response_payload(request_id, result))
            self._stdin.write(raw.encode("utf-8") + b"\n")
            await self._stdin.drain()
            return True
        except (BrokenPipeError, OSError) as e:
            logger.warning("async json-rpc send response failed: error=%s", e)
            return False

    async def send_error_response(
        self,
        request_id: object | None,
        code: int,
        message: str,
        data: object | None = None,
    ) -> bool:
        """Send a JSON-RPC error response for an unsupported/invalid request."""
        try:
            raw = json.dumps(_json_rpc_error_payload(request_id, code, message, data))
            self._stdin.write(raw.encode("utf-8") + b"\n")
            await self._stdin.drain()
            return True
        except (BrokenPipeError, OSError) as exc:
            logger.warning("async json-rpc send error response failed: error=%s", exc)
            return False

    async def _handle_notification(self, msg: JsonRpcMessage) -> None:
        """Handle incoming notification."""
        if self._callbacks.on_notification:
            cb = self._callbacks.on_notification
            should_stop = cb(msg.method or "", msg.params or {})
            if isinstance(should_stop, Awaitable):
                should_stop = await should_stop
            if should_stop:
                self._shutdown.set()
