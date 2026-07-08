from __future__ import annotations

import asyncio
import json
from typing import cast

import pytest

from app.application.json_rpc_client import (
    AsyncJsonRpcPeer,
    CommandExecutionRequestApproval,
    FileChangeRequestApproval,
    JsonRpcCallbacks,
    JsonRpcMessage,
    JsonRpcPeer,
    ServerRequest,
)


class _SyncWriter:
    def __init__(self) -> None:
        self.lines: list[bytes] = []

    def write(self, data: bytes) -> object:
        self.lines.append(data)
        return len(data)

    def flush(self) -> object:
        return None


class _SyncReader:
    def readline(self) -> bytes:
        return b""


class _AsyncWriter:
    def __init__(self) -> None:
        self.lines: list[bytes] = []

    def write(self, data: bytes) -> object:
        self.lines.append(data)
        return None

    async def drain(self) -> None:
        return None


def _sync_peer() -> JsonRpcPeer:
    return JsonRpcPeer(stdin=_SyncWriter(), stdout=_SyncReader())


def _async_peer(callbacks: JsonRpcCallbacks | None = None) -> AsyncJsonRpcPeer:
    return AsyncJsonRpcPeer(
        stdin=cast(asyncio.StreamWriter, _AsyncWriter()),
        stdout=cast(asyncio.StreamReader, object()),
        callbacks=callbacks,
    )


def _assert_message(actual: JsonRpcMessage | None, expected: JsonRpcMessage | None) -> None:
    assert actual == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            '{"jsonrpc":"2.0","id":7,"result":{"ok":true}}',
            JsonRpcMessage(type="response", request_id=7, result={"ok": True}, raw=""),
        ),
        (
            '{"jsonrpc":"2.0","id":"abc","error":{"code":-32601,"message":"missing"}}',
            JsonRpcMessage(
                type="error",
                request_id="abc",
                error={"code": -32601, "message": "missing"},
                raw="",
            ),
        ),
        (
            '{"jsonrpc":"2.0","id":3,"method":"thread/start","params":{"cwd":"/tmp"}}',
            JsonRpcMessage(
                type="request",
                method="thread/start",
                request_id=3,
                params={"cwd": "/tmp"},
                raw="",
            ),
        ),
        (
            '{"jsonrpc":"2.0","method":"turn/status","params":{"state":"running"}}',
            JsonRpcMessage(
                type="notification",
                method="turn/status",
                params={"state": "running"},
                raw="",
            ),
        ),
        ("not json", None),
        ("[]", None),
        ('{"jsonrpc":"2.0","result":{"missing":"id"}}', None),
        ('{"jsonrpc":"2.0","error":{"missing":"id"}}', None),
    ],
)
def test_sync_and_async_peers_share_json_rpc_parse_contract(
    line: str, expected: JsonRpcMessage | None
) -> None:
    sync_msg = _sync_peer()._parse_message(line)
    async_msg = _async_peer()._parse_message(line)
    if expected is not None:
        expected.raw = line
    _assert_message(sync_msg, expected)
    _assert_message(async_msg, expected)


@pytest.mark.parametrize(
    ("method", "params", "expected_type"),
    [
        ("file_change/request_approval", {"item_id": "file-1"}, FileChangeRequestApproval),
        ("command_execution/request_approval", {"item_id": "cmd-1"}, CommandExecutionRequestApproval),
        ("thread/start", {"thread_id": "t1"}, ServerRequest),
    ],
)
def test_server_request_mapping_is_shared_by_protocol_method(
    method: str,
    params: dict[str, object],
    expected_type: type[ServerRequest],
) -> None:
    message = JsonRpcMessage(type="request", method=method, request_id=12, params=params)
    request = _sync_peer()._create_server_request(message)

    assert isinstance(request, expected_type)
    assert request.request_id == 12
    assert request.method == method
    assert request.params == params
    if isinstance(request, (FileChangeRequestApproval, CommandExecutionRequestApproval)):
        assert request.item_id == params["item_id"]


def test_sync_peer_serializes_requests_notifications_and_responses_with_one_payload_contract() -> None:
    writer = _SyncWriter()
    peer = JsonRpcPeer(stdin=writer, stdout=_SyncReader())

    assert peer.send("thread/start", {"cwd": "/repo"}, request_id=4)
    assert peer.send("initialized")
    assert peer.send_response("req-1", {"accepted": True})

    payloads = [json.loads(line.decode("utf-8")) for line in writer.lines]
    assert payloads == [
        {"jsonrpc": "2.0", "method": "thread/start", "id": 4, "params": {"cwd": "/repo"}},
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "id": "req-1", "result": {"accepted": True}},
    ]


@pytest.mark.asyncio
async def test_async_peer_serializes_requests_notifications_and_responses_with_one_payload_contract() -> None:
    writer = _AsyncWriter()
    peer = AsyncJsonRpcPeer(
        stdin=cast(asyncio.StreamWriter, writer),
        stdout=cast(asyncio.StreamReader, object()),
    )

    assert await peer.send("thread/start", {"cwd": "/repo"}, request_id=4)
    assert await peer.send("initialized")
    assert await peer.send_response("req-1", {"accepted": True})

    payloads = [json.loads(line.decode("utf-8")) for line in writer.lines]
    assert payloads == [
        {"jsonrpc": "2.0", "method": "thread/start", "id": 4, "params": {"cwd": "/repo"}},
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "id": "req-1", "result": {"accepted": True}},
    ]


@pytest.mark.asyncio
async def test_async_notification_callback_can_stop_the_reader_like_sync_peer() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def on_notification(method: str, params: dict[str, object]) -> bool:
        calls.append((method, params))
        return True

    peer = _async_peer(callbacks=JsonRpcCallbacks(on_notification=on_notification))

    await peer._handle_notification(
        JsonRpcMessage(type="notification", method="turn/status", params={"state": "done"}),
    )

    assert calls == [("turn/status", {"state": "done"})]
    assert peer._shutdown.is_set()
