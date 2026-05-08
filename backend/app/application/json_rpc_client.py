"""
Minimal JSON-RPC 2.0 client for Codex app-server mode.

This module provides:
- JsonRpcPeer: Bidirectional JSON-RPC communication over stdin/stdout
- AsyncJsonRpcPeer: Async version of JsonRpcPeer using asyncio
- AppServerClient: High-level client implementing Codex app-server protocol
- Auto-approve for FileChangeRequestApproval and CommandExecutionRequestApproval

Based on the Rust implementation in vibe-kanban/crates/executors/src/executors/codex/
"""
import asyncio
import json
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


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
    request_id: Any = None
    params: dict | None = None
    result: Any = None
    error: dict | None = None
    raw: str = ""


@dataclass
class ServerRequest:
    """Base class for server-initiated requests from Codex."""
    request_id: Any
    method: str
    params: dict


@dataclass
class FileChangeRequestApproval(ServerRequest):
    """File change approval request (codex.apply_patch)."""
    item_id: str = ""


@dataclass
class CommandExecutionRequestApproval(ServerRequest):
    """Command execution approval request (codex.exec_command)."""
    item_id: str = ""


class Decision(str, Enum):
    """Approval decisions for server requests."""
    Accept = "accept"
    AcceptForSession = "acceptForSession"
    Decline = "decline"
    Cancel = "cancel"


@dataclass
class JsonRpcCallbacks:
    """Callbacks for handling JSON-RPC events. Override as needed."""
    on_notification: Callable[[str, dict], Any] | None = None  # Returns True to stop reading
    on_server_request: Callable[[ServerRequest], Any] | None = None  # Returns response or None
    on_response: Callable[[Any, Any], None] | None = None
    on_error: Callable[[Any, dict], None] | None = None
    on_raw_line: Callable[[str], Any] | None = None


class JsonRpcPeer:
    """
    Bidirectional JSON-RPC peer for Codex app-server communication.

    Handles:
    - Sending requests with unique IDs and waiting for responses
    - Receiving and dispatching notifications
    - Handling server-initiated requests (approvals)
    """

    def __init__(self, stdin, stdout, callbacks: JsonRpcCallbacks | None = None):
        self._stdin = stdin
        self._stdout = stdout
        self._callbacks = callbacks or JsonRpcCallbacks()
        self._pending: dict[Any, threading.Event] = {}
        self._pending_results: dict[Any, Any] = {}
        self._pending_errors: dict[Any, dict] = {}
        self._id_counter = 0
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._reader_thread: threading.Thread | None = None

    def start(self):
        """Start the reader thread."""
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self):
        """Stop the reader thread and signal shutdown."""
        self._shutdown.set()
        if self._reader_thread:
            self._reader_thread.join(timeout=5)

    def next_request_id(self) -> int:
        """Generate the next unique request ID."""
        with self._lock:
            self._id_counter += 1
            return self._id_counter

    def send(self, method: str, params: dict | None = None, request_id: int | None = None) -> bool:
        """Send a JSON-RPC request or notification."""
        if request_id is None:
            # Notification (no id)
            payload = {
                "jsonrpc": "2.0",
                "method": method,
            }
            if params is not None:
                payload["params"] = params
        else:
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params is not None:
                payload["params"] = params

        try:
            raw = json.dumps(payload)
            self._stdin.write(raw.encode("utf-8") + b"\n")
            self._stdin.flush()
            return True
        except (BrokenPipeError, OSError) as e:
            print(f"[JSON-RPC] Failed to send: {e}", flush=True)
            return False

    def request(self, method: str, params: dict | None = None, timeout: float = 600) -> Any:
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

    def _reader_loop(self):
        """Main loop that reads and dispatches JSON-RPC messages."""
        import sys
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

        except Exception as e:
            print(f"[JSON-RPC] Reader error: {e}", file=sys.stderr, flush=True)
        finally:
            self._shutdown.set()
            # Signal all pending waiters
            with self._lock:
                for evt in self._pending.values():
                    evt.set()

    def _parse_message(self, line: str) -> JsonRpcMessage | None:
        """Parse a JSON-RPC message from a raw line."""
        if not line.startswith("{"):
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        if "error" in data and "id" in data:
            return JsonRpcMessage(
                type="error",
                request_id=data.get("id"),
                error=data.get("error"),
                raw=line,
            )
        elif "id" in data and "result" in data:
            return JsonRpcMessage(
                type="response",
                request_id=data.get("id"),
                result=data.get("result"),
                raw=line,
            )
        elif "id" in data and "method" in data:
            return JsonRpcMessage(
                type="request",
                request_id=data.get("id"),
                method=data.get("method"),
                params=data.get("params"),
                raw=line,
            )
        elif "method" in data:
            return JsonRpcMessage(
                type="notification",
                method=data.get("method"),
                params=data.get("params"),
                raw=line,
            )
        return None

    def _handle_response(self, msg: JsonRpcMessage):
        """Handle an incoming JSON-RPC response."""
        if self._callbacks.on_response:
            self._callbacks.on_response(msg.request_id, msg.result)

        with self._lock:
            if msg.request_id in self._pending:
                self._pending_results[msg.request_id] = msg.result
                self._pending[msg.request_id].set()

    def _handle_error(self, msg: JsonRpcMessage):
        """Handle an incoming JSON-RPC error response."""
        if self._callbacks.on_error:
            self._callbacks.on_error(msg.request_id, msg.error)

        with self._lock:
            if msg.request_id in self._pending:
                self._pending_errors[msg.request_id] = msg.error
                self._pending[msg.request_id].set()

    def _handle_request(self, msg: JsonRpcMessage):
        """Handle an incoming JSON-RPC request from the server."""
        response = None
        if self._callbacks.on_server_request:
            server_req = self._create_server_request(msg)
            response = self._callbacks.on_server_request(server_req)

        # Send response if callback returned one
        if response is not None and msg.request_id is not None:
            self.send_response(msg.request_id, response)

    def _handle_notification(self, msg: JsonRpcMessage):
        """Handle an incoming JSON-RPC notification."""
        if self._callbacks.on_notification:
            should_stop = self._callbacks.on_notification(msg.method or "", msg.params or {})
            if should_stop:
                self._shutdown.set()

    def _create_server_request(self, msg: JsonRpcMessage) -> ServerRequest:
        """Create a ServerRequest object from a JSON-RPC request."""
        method = msg.method or ""
        params = msg.params or {}

        if method == "file_change/request_approval":
            return FileChangeRequestApproval(
                request_id=msg.request_id,
                method=method,
                params=params,
                item_id=params.get("item_id", ""),
            )
        elif method == "command_execution/request_approval":
            return CommandExecutionRequestApproval(
                request_id=msg.request_id,
                method=method,
                params=params,
                item_id=params.get("item_id", ""),
            )
        else:
            return ServerRequest(
                request_id=msg.request_id,
                method=method,
                params=params,
            )

    def send_response(self, request_id: Any, result: Any) -> bool:
        """Send a JSON-RPC response."""
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        try:
            raw = json.dumps(payload)
            self._stdin.write(raw.encode("utf-8") + b"\n")
            self._stdin.flush()
            return True
        except (BrokenPipeError, OSError) as e:
            print(f"[JSON-RPC] Failed to send response: {e}", flush=True)
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
        codex_store,
        log_store,
        event_bus=None,
        notification_callback: Callable[[str, dict], Any] | None = None,
        auto_approve: bool = True,
        plan_mode: bool = False,
    ):
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
        self._approval_callback: Callable[[str, ServerRequest], Any] | None = None

    def attach_peer(self, peer: JsonRpcPeer | AsyncJsonRpcPeer):
        """Attach a JsonRpcPeer or AsyncJsonRpcPeer to this client."""
        self._peer = peer
        existing_callbacks = peer._callbacks or JsonRpcCallbacks()
        self._callbacks = self._create_callbacks(existing_callbacks)
        peer._callbacks = self._callbacks

    def _create_callbacks(self, existing_callbacks: JsonRpcCallbacks | None = None) -> JsonRpcCallbacks:
        """Create callbacks for JSON-RPC events."""
        existing_callbacks = existing_callbacks or JsonRpcCallbacks()
        return JsonRpcCallbacks(
            on_notification=self._on_notification,
            on_server_request=self._on_server_request,
            on_response=self._on_response,
            on_error=self._on_error,
            on_raw_line=existing_callbacks.on_raw_line,
        )

    async def initialize(self) -> dict:
        """
        Send initialize request to Codex app-server.

        Returns the InitializeResponse.
        """
        params = {
            "clientInfo": {
                "name": "agent-collab-console",
                "version": "1.0.0",
            },
            "capabilities": {
                "experimentalApi": True,
            },
        }
        if isinstance(self._peer, AsyncJsonRpcPeer):
            result = await self._peer.request("initialize", params)
        else:
            result = self._peer.request("initialize", params)
        return result or {}

    async def initialized(self) -> bool:
        """Send initialized notification."""
        if isinstance(self._peer, AsyncJsonRpcPeer):
            return await self._peer.send("initialized")
        else:
            return self._peer.send("initialized")

    async def thread_start(self, prompt: str | None = None) -> dict:
        """
        Start a new thread.

        Args:
            prompt: Optional initial prompt for the thread

        Returns the ThreadStartResponse with thread_id.
        """
        params = {}
        if prompt:
            params["input"] = [{"type": "text", "text": prompt, "text_elements": []}]

        if isinstance(self._peer, AsyncJsonRpcPeer):
            result = await self._peer.request("thread/start", params)
        else:
            result = self._peer.request("thread/start", params)

        if result:
            if "thread_id" in result:
                self._thread_id = result["thread_id"]
            elif "thread" in result and "id" in result["thread"]:
                self._thread_id = result["thread"]["id"]
        return result or {}

    async def thread_fork(self, thread_id: str) -> dict:
        """
        Fork an existing thread to create a new session.

        Args:
            thread_id: The thread ID to fork from

        Returns the ThreadForkResponse with new thread_id.
        """
        params = {"threadId": thread_id}
        if isinstance(self._peer, AsyncJsonRpcPeer):
            result = await self._peer.request("thread/fork", params)
        else:
            result = self._peer.request("thread/fork", params)

        if result:
            if "thread_id" in result:
                self._thread_id = result["thread_id"]
            elif "thread" in result and "id" in result["thread"]:
                self._thread_id = result["thread"]["id"]
        return result or {}

    async def turn_start(self, prompt: str, thread_id: str | None = None) -> dict:
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

        params = {
            "threadId": tid,
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
        }
        if isinstance(self._peer, AsyncJsonRpcPeer):
            return await self._peer.request("turn/start", params) or {}
        else:
            return self._peer.request("turn/start", params) or {}

    async def _on_notification(self, method: str, params: dict) -> bool:
        """
        Handle incoming notifications.

        Returns True to stop the reader loop (e.g., on shutdown).
        """
        import sys
        print(f"[JSON-RPC] Notification: {method} {params}", file=sys.stderr, flush=True)

        # Log all notifications
        if self._event_bus:
            payload = {
                "type": "notification",
                "method": method,
                "params": params,
            }
            if hasattr(self._event_bus, "append") and asyncio.iscoroutinefunction(self._event_bus.append):
                await self._event_bus.append(payload)
            else:
                self._event_bus.append(payload)

        if self._notification_callback:
            if asyncio.iscoroutinefunction(self._notification_callback):
                should_stop = await self._notification_callback(method, params)
            else:
                should_stop = self._notification_callback(method, params)
            if should_stop:
                return True

        return False

    async def _on_server_request(self, request: ServerRequest) -> dict | None:
        """
        Handle server-initiated requests (approvals).

        In auto_approve mode (Phase 1): returns decision immediately.
        In manual mode (Phase 2): stores request and emits SSE event, returns None.
        """
        import sys
        print(f"[JSON-RPC] Server request: {request.method} {request.params}", file=sys.stderr, flush=True)

        # Log the approval request
        if self._event_bus:
            payload = {
                "type": "server_request",
                "method": request.method,
                "params": request.params,
            }
            if hasattr(self._event_bus, "append") and asyncio.iscoroutinefunction(self._event_bus.append):
                await self._event_bus.append(payload)
            else:
                self._event_bus.append(payload)

        # Auto-approve for Phase 1
        if self._auto_approve:
            if isinstance(request, FileChangeRequestApproval):
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

    def set_approval_callback(self, callback: Callable[[str, ServerRequest], Any]):
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
            print(f"[JSON-RPC] No pending approval found for item_id={item_id}", flush=True)
            return False

        response = {"decision": decision}
        if self._peer:
            if isinstance(self._peer, AsyncJsonRpcPeer):
                await self._peer.send_response(request.request_id, response)
            else:
                self._peer.send_response(request.request_id, response)
            print(f"[JSON-RPC] Resolved approval {item_id} with decision={decision}", flush=True)
        return True

    def get_pending_approvals(self) -> dict[str, ServerRequest]:
        """Return all pending approval requests."""
        return self._pending_approvals.copy()

    def _on_response(self, request_id: Any, result: Any):
        """Handle incoming responses."""
        import sys
        print(f"[JSON-RPC] Response {request_id}: {result}", file=sys.stderr, flush=True)

    def _on_error(self, request_id: Any, error: dict):
        """Handle incoming error responses."""
        import sys
        print(f"[JSON-RPC] Error {request_id}: {error}", file=sys.stderr, flush=True)


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

    def __init__(self, stdin: asyncio.StreamWriter, stdout: asyncio.StreamReader, callbacks: JsonRpcCallbacks | None = None):
        self._stdin = stdin
        self._stdout = stdout
        self._callbacks = callbacks or JsonRpcCallbacks()
        self._pending: dict[Any, asyncio.Event] = {}
        self._pending_results: dict[Any, Any] = {}
        self._pending_errors: dict[Any, dict] = {}
        self._id_counter = 0
        self._lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self._reader_task: asyncio.Task | None = None

    async def start(self):
        """Start the async reader task."""
        self._reader_task = asyncio.create_task(self._async_reader_loop())

    async def stop(self):
        """Stop the reader task and signal shutdown."""
        self._shutdown.set()
        if self._reader_task:
            try:
                await asyncio.wait_for(self._reader_task, timeout=5)
            except asyncio.TimeoutError:
                self._reader_task.cancel()

    async def next_request_id(self) -> int:
        """Generate the next unique request ID."""
        async with self._lock:
            self._id_counter += 1
            return self._id_counter

    async def send(self, method: str, params: dict | None = None, request_id: int | None = None) -> bool:
        """Send a JSON-RPC request or notification."""
        if request_id is None:
            payload = {
                "jsonrpc": "2.0",
                "method": method,
            }
            if params is not None:
                payload["params"] = params
        else:
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params is not None:
                payload["params"] = params

        try:
            raw = json.dumps(payload)
            self._stdin.write(raw.encode("utf-8") + b"\n")
            await self._stdin.drain()
            return True
        except (BrokenPipeError, OSError) as e:
            print(f"[AsyncJSON-RPC] Failed to send: {e}", flush=True)
            return False

    async def request(self, method: str, params: dict | None = None, timeout: float = 600) -> Any:
        """Send a JSON-RPC request and wait for response."""
        request_id = await self.next_request_id()
        evt = asyncio.Event()

        async with self._lock:
            self._pending[request_id] = evt

        try:
            await self.send(method, params, request_id)
            try:
                await asyncio.wait_for(evt.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                raise TimeoutError(f"Request {method} timed out after {timeout}s")

            if request_id in self._pending_errors:
                error = self._pending_errors.pop(request_id)
                raise Exception(f"JSON-RPC error: {error}")

            return self._pending_results.get(request_id)
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)
                self._pending_results.pop(request_id, None)
                self._pending_errors.pop(request_id, None)

    async def _async_reader_loop(self):
        """Async main loop that reads and dispatches JSON-RPC messages."""
        import sys
        try:
            while not self._shutdown.is_set():
                try:
                    raw_line = await asyncio.wait_for(self._stdout.readline(), timeout=1)
                except asyncio.TimeoutError:
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
        except Exception as e:
            print(f"[AsyncJSON-RPC] Reader error: {e}", file=sys.stderr, flush=True)
        finally:
            self._shutdown.set()
            async with self._lock:
                for evt in self._pending.values():
                    evt.set()

    def _parse_message(self, line: str) -> JsonRpcMessage | None:
        """Parse a JSON-RPC message from a line."""
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(parsed, dict):
            return None

        msg_type = None
        if "result" in parsed:
            msg_type = "response"
        elif "error" in parsed:
            msg_type = "error"
        elif "method" in parsed:
            msg_id = parsed.get("id")
            if msg_id is None:
                msg_type = "notification"
            else:
                msg_type = "request"
        else:
            return None

        return JsonRpcMessage(
            type=msg_type,
            method=parsed.get("method"),
            request_id=parsed.get("id"),
            params=parsed.get("params"),
            result=parsed.get("result"),
            error=parsed.get("error"),
            raw=line,
        )

    async def _handle_response(self, msg: JsonRpcMessage):
        """Handle incoming response."""
        if self._callbacks.on_response:
            self._callbacks.on_response(msg.request_id, msg.result)
        async with self._lock:
            if msg.request_id in self._pending:
                self._pending_results[msg.request_id] = msg.result
                self._pending[msg.request_id].set()

    async def _handle_error(self, msg: JsonRpcMessage):
        """Handle incoming error response."""
        if self._callbacks.on_error:
            self._callbacks.on_error(msg.request_id, msg.error)
        async with self._lock:
            if msg.request_id in self._pending:
                self._pending_errors[msg.request_id] = msg.error
                self._pending[msg.request_id].set()

    async def _handle_request(self, msg: JsonRpcMessage):
        """Handle incoming request from server."""
        if self._callbacks.on_server_request:
            cb = self._callbacks.on_server_request
            # Create a proper ServerRequest object
            method = msg.method or ""
            params = msg.params or {}
            
            if method == "file_change/request_approval":
                request = FileChangeRequestApproval(
                    request_id=msg.request_id,
                    method=method,
                    params=params,
                    item_id=params.get("item_id", ""),
                )
            elif method == "command_execution/request_approval":
                request = CommandExecutionRequestApproval(
                    request_id=msg.request_id,
                    method=method,
                    params=params,
                    item_id=params.get("item_id", ""),
                )
            else:
                request = ServerRequest(
                    request_id=msg.request_id,
                    method=method,
                    params=params,
                )

            if asyncio.iscoroutinefunction(cb):
                response = await cb(request)
            else:
                response = cb(request)
                
            if response is not None:
                await self.send_response(msg.request_id, response)

    async def send_response(self, request_id: Any, result: Any) -> bool:
        """Send a JSON-RPC response."""
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        try:
            raw = json.dumps(payload)
            self._stdin.write(raw.encode("utf-8") + b"\n")
            await self._stdin.drain()
            return True
        except (BrokenPipeError, OSError) as e:
            print(f"[AsyncJSON-RPC] Failed to send response: {e}", flush=True)
            return False

    async def _handle_notification(self, msg: JsonRpcMessage):
        """Handle incoming notification."""
        if self._callbacks.on_notification:
            cb = self._callbacks.on_notification
            if asyncio.iscoroutinefunction(cb):
                await cb(msg.method or "", msg.params or {})
            else:
                cb(msg.method or "", msg.params or {})
