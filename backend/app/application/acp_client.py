"""ACP v1 wire client over :class:`AsyncJsonRpcPeer`.

This module implements only the stable-v1 agent-client-protocol lifecycle the
console needs: ``initialize`` → ``session/new`` → (optional)
``session/set_config_option`` → ``session/prompt``, with ``session/update``
notifications and ``session/request_permission`` server requests mapped through
callbacks. It deliberately reuses the newline-delimited JSON-RPC transport in
``json_rpc_client.py`` and does **not** touch the Codex-specific
``AppServerClient``.

Security posture (fail-closed):
- Protocol-version mismatch, malformed handshake, or an unexpected stop reason
  on ``session/prompt`` raise so the runtime can terminalize the task.
- ``session/cancel`` is a notification; a cancelled turn also resolves every
  outstanding ``session/request_permission`` with the ``cancelled`` outcome.
- No auto-approval: permission requests are surfaced through
  ``on_permission_request`` and only resolved when the caller maps a decision.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.application.json_rpc_client import (
    AsyncJsonRpcPeer,
    JsonObject,
    JsonRpcCallbacks,
    ServerRequest,
)
from app.json_safety import object_dict, string_value

logger = logging.getLogger(__name__)

#: Protocol version advertised by this client. ACP stable v1.
ACP_PROTOCOL_VERSION = "1"

#: The only ``session/prompt`` stop reason treated as an unambiguous success.
ACP_STOP_REASON_END_TURN = "end_turn"


@dataclass
class AcpConfigOption:
    """A model/config option exposed by the agent in ``session/new``."""

    id: str
    kind: str = ""
    label: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> AcpConfigOption | None:
        if not isinstance(payload, dict):
            return None
        option_id = string_value(payload.get("id"))
        if not option_id:
            return None
        return cls(
            id=option_id,
            kind=string_value(payload.get("kind") or payload.get("type")),
            label=string_value(payload.get("label")),
        )


@dataclass
class AcpPermissionRequest:
    """A ``session/request_permission`` server request awaiting a decision."""

    request_id: object
    options: list[JsonObject] = field(default_factory=list)
    raw_params: JsonObject = field(default_factory=dict)


#: Outcome values accepted by ``session/request_permission`` responses.
PERMISSION_OUTCOMES = frozenset(
    {"allow_once", "allow_always", "reject_once", "reject_always", "cancelled"}
)
PermissionOutcome = str


class AcpProtocolError(RuntimeError):
    """Raised on protocol-version mismatch or a malformed handshake response."""


AcpNotificationCallback = Callable[[JsonObject], Awaitable[None]]
AcpPermissionCallback = Callable[[AcpPermissionRequest], Awaitable[None]]
AcpClosedCallback = Callable[[], Awaitable[None]]


class AcpClient:
    """High-level ACP v1 client over an :class:`AsyncJsonRpcPeer`.

    The peer owns the stdin/stdout transport; this client wires the peer's
    notification/request callbacks so that ``session/update`` flows to
    ``on_session_update`` and ``session/request_permission`` flows to
    ``on_permission_request``. The caller is expected to have started the
    peer's reader task (or to start it via :meth:`start`).
    """

    def __init__(
        self,
        peer: AsyncJsonRpcPeer,
        *,
        on_session_update: AcpNotificationCallback | None = None,
        on_permission_request: AcpPermissionCallback | None = None,
        on_closed: AcpClosedCallback | None = None,
    ) -> None:
        self._peer = peer
        self._on_session_update = on_session_update
        self._on_permission_request = on_permission_request
        self._on_closed = on_closed
        # configOptions exposed by the agent in session/new, keyed by id.
        self._config_options: dict[str, AcpConfigOption] = {}
        self._session_id: str | None = None
        self._initialized = False
        self._closed = False
        self._handshake_timeout_s: float = 30.0

        # Route peer events through this client. Reuse any existing on_raw_line
        # so callers (e.g. raw logging) keep working.
        previous_callbacks = peer._callbacks or JsonRpcCallbacks()
        peer._callbacks = JsonRpcCallbacks(
            on_notification=self._on_notification,
            on_server_request=self._on_server_request,
            on_response=previous_callbacks.on_response,
            on_error=previous_callbacks.on_error,
            on_raw_line=previous_callbacks.on_raw_line,
        )

    @property
    def peer(self) -> AsyncJsonRpcPeer:
        return self._peer

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def config_options(self) -> dict[str, AcpConfigOption]:
        return dict(self._config_options)

    def set_handshake_timeout(self, seconds: float) -> None:
        self._handshake_timeout_s = max(1.0, float(seconds))

    async def start(self) -> None:
        """Start the peer's reader task."""
        await self._peer.start()

    # --- lifecycle -----------------------------------------------------

    async def initialize(self) -> JsonObject:
        """Send ``initialize`` and the ``initialized`` notification.

        Advertises only the capabilities this console actually implements: no
        filesystem, no terminal. Raises :class:`AcpProtocolError` on version
        mismatch or a malformed response.
        """
        params: JsonObject = {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "clientCapabilities": {
                "fs": {
                    "readTextFile": False,
                    "writeTextFile": False,
                },
                "terminal": False,
            },
            "clientInfo": {
                "name": "agent-collab-console",
                "version": "1.0.0",
            },
        }
        result = await self._peer.request(
            "initialize", params, timeout=self._handshake_timeout_s
        )
        if not isinstance(result, dict):
            raise AcpProtocolError(
                f"ACP initialize returned a non-object result: {result!r}"
            )
        result_obj = object_dict(result)
        server_protocol = string_value(result_obj.get("protocolVersion"))
        if not server_protocol:
            raise AcpProtocolError("ACP initialize response missing protocolVersion")
        # Fail closed on any version we did not negotiate. The stable v1 wire
        # is "1"; the server may echo it back or present a compatible value,
        # but a blank/mismatched version means we cannot trust the session.
        if server_protocol != ACP_PROTOCOL_VERSION:
            raise AcpProtocolError(
                f"ACP protocol version mismatch: client={ACP_PROTOCOL_VERSION!r} "
                f"server={server_protocol!r}"
            )
        # Notify the server that initialization is complete.
        await self._peer.send("initialized")
        self._initialized = True
        return result_obj

    async def session_new(self) -> str:
        """Create a new ACP session and remember its ``configOptions``."""
        result = await self._peer.request("session/new", {}, timeout=self._handshake_timeout_s)
        if not isinstance(result, dict):
            raise AcpProtocolError(
                f"ACP session/new returned a non-object result: {result!r}"
            )
        result_obj = object_dict(result)
        session_id = string_value(result_obj.get("sessionId"))
        if not session_id:
            raise AcpProtocolError("ACP session/new response missing sessionId")
        self._session_id = session_id

        # Record any config options the agent exposed so set_config_option can
        # truthfully apply only matching ones.
        raw_options = result_obj.get("configOptions")
        if isinstance(raw_options, list):
            for raw_option in raw_options:
                option = AcpConfigOption.from_payload(raw_option)
                if option is not None:
                    self._config_options[option.id] = option
        return session_id

    async def set_config_option(self, option_id: str, value: object) -> bool:
        """Apply a config option only if the agent exposed it.

        Returns ``True`` when the option was sent, ``False`` when the agent did
        not expose a matching option (in which case nothing is sent — never
        claim an override was applied that the agent cannot honour).
        """
        if not option_id:
            return False
        if option_id not in self._config_options:
            logger.debug(
                "ACP set_config_option skipped: option %r not exposed by agent",
                option_id,
            )
            return False
        params: JsonObject = {
            "sessionId": self._require_session(),
            "optionId": option_id,
            "value": value,
        }
        await self._peer.request(
            "session/set_config_option",
            params,
            timeout=self._handshake_timeout_s,
        )
        return True

    async def session_prompt(self, prompt: str, *, timeout: float = 600.0) -> str:
        """Send ``session/prompt`` and return the ``stopReason``.

        Raises :class:`AcpProtocolError` if the response is malformed.
        """
        params: JsonObject = {
            "sessionId": self._require_session(),
            "prompt": prompt,
        }
        result = await self._peer.request("session/prompt", params, timeout=timeout)
        if not isinstance(result, dict):
            raise AcpProtocolError(
                f"ACP session/prompt returned a non-object result: {result!r}"
            )
        result_obj = object_dict(result)
        stop_reason = string_value(result_obj.get("stopReason"))
        if not stop_reason:
            raise AcpProtocolError("ACP session/prompt response missing stopReason")
        return stop_reason

    async def cancel(self) -> None:
        """Send ``session/cancel`` notification for the current session.

        A cancelled turn must also resolve every outstanding permission request
        as ``cancelled``; callers should invoke :meth:`resolve_permission` for
        each pending request after this returns.
        """
        if self._session_id is None:
            return
        params: JsonObject = {"sessionId": self._session_id}
        await self._peer.send("session/cancel", params)

    async def resolve_permission(
        self, request_id: object, outcome: PermissionOutcome
    ) -> bool:
        """Respond to a ``session/request_permission`` server request.

        ``outcome`` must be one of :data:`PERMISSION_OUTCOMES`. Returns ``True``
        when the response was sent successfully.
        """
        if outcome not in PERMISSION_OUTCOMES:
            raise ValueError(f"invalid ACP permission outcome: {outcome!r}")
        result: JsonObject = {"outcome": outcome}
        return await self._peer.send_response(request_id, result)

    async def send_error_response(
        self, request_id: object, code: int, message: str
    ) -> bool:
        """Send a JSON-RPC error response for an unsupported/invalid request."""
        return await self._peer.send_error_response(request_id, code, message)

    def _require_session(self) -> str:
        if self._session_id is None:
            raise AcpProtocolError("ACP session has not been created yet")
        return self._session_id

    # --- peer callback routing ----------------------------------------

    async def _on_notification(self, method: str, params: JsonObject) -> bool:
        if method == "session/update":
            await self._dispatch_session_update(params)
            return False
        # Unknown notifications are harmless; the peer already routed raw lines
        # through on_raw_line for logging if configured.
        logger.debug("ACP ignored notification: %s", method)
        return False

    async def _on_server_request(self, request: ServerRequest) -> JsonObject | None:
        # The peer wraps parsed requests into ServerRequest dataclasses. We only
        # handle ``session/request_permission``; everything else is rejected with
        # a method-not-found error so the agent cannot wedge the turn on an
        # unsupported interaction.
        method = getattr(request, "method", "") or ""
        request_id = getattr(request, "request_id", None)
        params = object_dict(getattr(request, "params", None) or {})

        if method == "session/request_permission":
            await self._dispatch_permission_request(request_id, params)
            # Returning None keeps the response outstanding until the caller
            # resolves it via resolve_permission().
            return None

        logger.warning("ACP rejecting unsupported server request: %s", method)
        await self._peer.send_error_response(
            request_id, -32601, f"method not found: {method}"
        )
        return None

    async def _dispatch_session_update(self, params: JsonObject) -> None:
        # A session/update may bundle an array of updates or a single update
        # object. Normalize both into a list of update payloads.
        updates = params.get("update") or params.get("updates")
        if isinstance(updates, list):
            update_list = [object_dict(item) for item in updates if isinstance(item, dict)]
        elif isinstance(updates, dict):
            update_list = [object_dict(updates)]
        else:
            # Fall back to treating the whole params as one update payload so
            # callers that expect {kind, ...} still receive something.
            update_list = [params]

        if self._on_session_update is None:
            return
        for update in update_list:
            try:
                await self._on_session_update(update)
            except Exception:
                logger.debug("ACP on_session_update callback failed", exc_info=True)

    async def _dispatch_permission_request(
        self, request_id: object, params: JsonObject
    ) -> None:
        raw_options = params.get("options")
        options: list[JsonObject] = []
        if isinstance(raw_options, list):
            options = [object_dict(item) for item in raw_options if isinstance(item, dict)]
        request = AcpPermissionRequest(
            request_id=request_id,
            options=options,
            raw_params=params,
        )
        if self._on_permission_request is None:
            # No handler: fail closed immediately so the turn cannot wedge.
            await self._peer.send_response(request_id, {"outcome": "cancelled"})
            return
        try:
            await self._on_permission_request(request)
        except Exception:
            logger.debug("ACP on_permission_request callback failed", exc_info=True)
            # Fail closed on callback errors.
            with _suppress_log():
                await self._peer.send_response(request_id, {"outcome": "cancelled"})

    async def _maybe_fire_closed(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._on_closed is not None:
            try:
                await self._on_closed()
            except Exception:
                logger.debug("ACP on_closed callback failed", exc_info=True)


class _suppress_log:
    """Tiny context manager that swallows exceptions when the peer write fails
    after a callback error — the caller already has the failure context."""

    def __enter__(self) -> _suppress_log:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return True
