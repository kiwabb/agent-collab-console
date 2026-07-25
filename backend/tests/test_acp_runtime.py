"""Tests for the ACP v1 runtime adapter.

Covers (per the PRD acceptance criteria):
- AcpClient wire lifecycle: initialize (version mismatch raises), session/new,
  optional model config option (only applied when exposed), session/prompt
  (only ``end_turn`` is success), permission resolution, cancel.
- AcpProcessRuntime security: ``_build_env`` fail-closed on missing allowlisted
  env vars, no env values stored, decision -> ACP outcome mapping, catalog
  resolution by executor id, permission timeout resolves as cancelled.
- RuntimeCatalogService ACP validation + resolve_effective_config (acp branch,
  conductor cannot select acp).
- A fake ACP v1 subprocess proving initialize -> session/new -> model option ->
  session/prompt produces persisted assistant output plus structured
  thought/tool events.
- Failure paths: protocol-version mismatch, process exit before handshake,
  missing allowlisted env var rejects launch.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from app.application.acp_client import (
    ACP_PROTOCOL_VERSION,
    ACP_STOP_REASON_END_TURN,
    PERMISSION_OUTCOMES,
    AcpClient,
    AcpProtocolError,
)
from app.application.acp_process_runtime import AcpProcessRuntime
from app.application.json_rpc_client import AsyncJsonRpcPeer
from app.application.process_runtime_common import (
    RuntimeCodexStore,
)
from app.application.runtime_catalog_service import (
    RuntimeCatalogService,
    RuntimeCatalogValidationError,
)
from app.domain.models import (
    AcpRuntimeConfig,
    CodexSession,
    CodexTask,
    ExecutionProcess,
    RuntimeCatalog,
    RuntimeExecutorConfig,
)

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Parametrizable fake ACP v1 server (real subprocess) for AcpClient wire tests.
# Driven by env vars so a single script covers every wire scenario without any
# fragile in-memory asyncio pipe plumbing.
# ---------------------------------------------------------------------------


_FAKE_ACP_SERVER_SRC = textwrap.dedent(
    """
    import json
    import os
    import sys

    PROTOCOL_VERSION = os.environ.get("ACP_TEST_PROTOCOL_VERSION", "1")
    STOP_REASON = os.environ.get("ACP_TEST_STOP_REASON", "end_turn")
    EXPOSE_MODEL_OPTION = os.environ.get("ACP_TEST_EXPOSE_MODEL") == "1"
    SEND_PERMISSION = os.environ.get("ACP_TEST_SEND_PERMISSION") == "1"


    def send(msg):
        sys.stdout.write(json.dumps(msg) + "\\n")
        sys.stdout.flush()


    def main():
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            method = msg.get("method")
            mid = msg.get("id")
            if method == "initialize":
                send({"jsonrpc": "2.0", "id": mid,
                      "result": {"protocolVersion": PROTOCOL_VERSION}})
            elif method == "initialized":
                continue
            elif method == "session/new":
                result = {"sessionId": "sess-123"}
                if EXPOSE_MODEL_OPTION:
                    result["configOptions"] = [{"id": "model", "kind": "string"}]
                send({"jsonrpc": "2.0", "id": mid, "result": result})
            elif method == "session/set_config_option":
                send({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "session/prompt":
                if SEND_PERMISSION:
                    send({"jsonrpc": "2.0", "id": "perm-1",
                          "method": "session/request_permission",
                          "params": {"options": [{"kind": "allow_once"},
                                                 {"kind": "reject_once"}]}})
                for update in [
                    {"kind": "thought", "thought": "planning"},
                    {"kind": "tool", "id": "tu-1", "name": "read_file",
                     "state": "completed"},
                    {"kind": "message", "role": "assistant",
                     "content": [{"type": "text", "text": "Hello from ACP"}]},
                ]:
                    send({"jsonrpc": "2.0", "method": "session/update",
                          "params": {"update": update}})
                send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": STOP_REASON}})
            elif method == "session/cancel":
                continue
            else:
                send({"jsonrpc": "2.0", "id": mid,
                      "error": {"code": -32601, "message": "method not found"}})

    main()
    """
)


def _write_fake_server(tmp_path: Path) -> Path:
    server_path = tmp_path / "fake_acp_server.py"
    server_path.write_text(_FAKE_ACP_SERVER_SRC, encoding="utf-8")
    return server_path


async def _spawn_fake_acp(server_path: Path, *, env_overrides: dict[str, str] | None = None):
    """Spawn the fake ACP server and wrap its stdin/stdout in an AcpClient.

    Returns ``(client, proc)``. The caller must terminate ``proc`` when done.
    """
    env = {"PATH": os.environ.get("PATH", os.defpath)}
    if env_overrides:
        env.update(env_overrides)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(server_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    assert proc.stdin is not None and proc.stdout is not None
    peer = AsyncJsonRpcPeer(stdin=proc.stdin, stdout=proc.stdout)
    client = AcpClient(peer)
    await peer.start()
    return client, proc


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    from contextlib import suppress

    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
    except TimeoutError:
        with suppress(Exception):
            proc.kill()


# ---------------------------------------------------------------------------
# AcpClient wire tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acp_client_initialize_version_mismatch_raises(tmp_path) -> None:
    server_path = _write_fake_server(tmp_path)
    client, proc = await _spawn_fake_acp(
        server_path, env_overrides={"ACP_TEST_PROTOCOL_VERSION": "999"}
    )
    try:
        with pytest.raises(AcpProtocolError, match="protocol version mismatch"):
            await client.initialize()
    finally:
        await _terminate(proc)


@pytest.mark.asyncio
async def test_acp_client_full_handshake_and_prompt_end_turn(tmp_path) -> None:
    server_path = _write_fake_server(tmp_path)
    client, proc = await _spawn_fake_acp(
        server_path,
        env_overrides={"ACP_TEST_EXPOSE_MODEL": "1"},
    )
    seen_updates: list[dict[str, object]] = []

    async def on_update(update: dict[str, object]) -> None:
        seen_updates.append(update)

    client._on_session_update = on_update  # type: ignore[assignment]
    try:
        result = await client.initialize()
        assert result["protocolVersion"] == ACP_PROTOCOL_VERSION
        session_id = await client.session_new()
        assert session_id == "sess-123"
        assert "model" in client.config_options
        # Model option applied only because the agent exposed it.
        applied = await client.set_config_option("model", "claude-sonnet-4-6")
        assert applied is True
        # Non-exposed option must NOT be sent.
        not_applied = await client.set_config_option("nonexistent", "x")
        assert not_applied is False
        stop_reason = await client.session_prompt("do the thing", timeout=5)
        assert stop_reason == ACP_STOP_REASON_END_TURN
    finally:
        await _terminate(proc)

    # The three session/update payloads should have been dispatched in order.
    kinds = [str(u.get("kind")) for u in seen_updates]
    assert kinds == ["thought", "tool", "message"]


@pytest.mark.asyncio
async def test_acp_client_non_end_turn_stop_reason_is_returned_not_raised(tmp_path) -> None:
    """A non-end_turn stop reason is surfaced to the runtime (which fails the
    task); the client itself just returns the value. This keeps fail-closed
    logic in the runtime where the ExecutionProcess lives."""
    server_path = _write_fake_server(tmp_path)
    client, proc = await _spawn_fake_acp(
        server_path, env_overrides={"ACP_TEST_STOP_REASON": "refusal"}
    )
    try:
        await client.initialize()
        await client.session_new()
        stop_reason = await client.session_prompt("hi", timeout=5)
        assert stop_reason == "refusal"
        assert stop_reason != ACP_STOP_REASON_END_TURN
    finally:
        await _terminate(proc)


@pytest.mark.asyncio
async def test_acp_client_permission_resolution_sends_outcome(tmp_path) -> None:
    server_path = _write_fake_server(tmp_path)
    client, proc = await _spawn_fake_acp(
        server_path, env_overrides={"ACP_TEST_SEND_PERMISSION": "1"}
    )
    received_permissions: list[object] = []

    async def on_permission(request) -> None:
        received_permissions.append(request)
        # Caller maps a human decision to an ACP outcome and resolves it.
        await client.resolve_permission(request.request_id, "allow_once")

    client._on_permission_request = on_permission  # type: ignore[assignment]
    try:
        await client.initialize()
        await client.session_new()
        # The server emits a permission request during session/prompt; the
        # callback resolves it. The prompt still completes with end_turn.
        await client.session_prompt("hi", timeout=5)
    finally:
        await _terminate(proc)

    assert len(received_permissions) == 1
    perm = received_permissions[0]
    assert perm.options == [{"kind": "allow_once"}, {"kind": "reject_once"}]


def test_acp_permission_outcomes_are_complete() -> None:
    assert frozenset(
        {"allow_once", "allow_always", "reject_once", "reject_always", "cancelled"}
    ) == PERMISSION_OUTCOMES


def test_acp_client_resolve_permission_rejects_invalid_outcome(tmp_path) -> None:
    """resolve_permission validates the outcome before any IO, so a bogus value
    raises ValueError without needing a live server."""
    server_path = _write_fake_server(tmp_path)

    async def run() -> None:
        client, proc = await _spawn_fake_acp(server_path)
        try:
            with pytest.raises(ValueError, match="invalid ACP permission outcome"):
                await client.resolve_permission("rid", "bogus")
        finally:
            await _terminate(proc)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Fake store + log/event sinks for AcpProcessRuntime unit tests.
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal RuntimeCodexStore for AcpProcessRuntime unit tests."""

    def __init__(self, *, task: CodexTask | None = None, workspace: CodexSession | None = None) -> None:
        self._task = task
        self._workspace = workspace or CodexSession(
            id="ws-1", title="ws", cwd="/tmp/acp-worktree"
        )
        self.saved_tasks: list[CodexTask] = []
        self.saved_workspaces: list[CodexSession] = []
        self.process_status_updates: list[tuple[str, str]] = []
        self.messages: list[object] = []

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        if workspace_id == self._workspace.id:
            return self._workspace
        return None

    async def save_codex_workspace(self, workspace: CodexSession) -> None:
        self.saved_workspaces.append(workspace)

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        if self._task is not None and task_id == self._task.id:
            return self._task
        return None

    async def save_codex_task(self, task: CodexTask) -> None:
        self.saved_tasks.append(task)
        self._task = task

    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        self.process_status_updates.append((process_id, status))

    async def load_execution_process(self, process_id: str) -> ExecutionProcess | None:
        return None

    async def list_codex_task_messages(
        self, task_id: str, execution_process_id: str | None = None
    ) -> list[object]:
        return list(self.messages)

    async def update_execution_process_usage(self, *args: object, **kwargs: object) -> None:
        return None

    async def save_codex_task_message(self, message: object) -> None:
        self.messages.append(message)

    async def load_help_request(self, help_request_id: str) -> object | None:
        return None


class _RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)

    async def queue_log_event(self, event: object) -> None:
        return None



# ---------------------------------------------------------------------------
# AcpProcessRuntime unit tests (no real subprocess)
# ---------------------------------------------------------------------------


def _make_runtime(
    *,
    catalog: RuntimeCatalog,
    task: CodexTask | None = None,
    workspace: CodexSession | None = None,
) -> tuple[AcpProcessRuntime, _FakeStore, _RecordingEventBus]:
    store = _FakeStore(task=task, workspace=workspace)

    async def loader() -> RuntimeCatalog:
        return catalog

    event_bus = _RecordingEventBus()
    runtime = AcpProcessRuntime(
        codex_store=cast(RuntimeCodexStore, store),
        log_store=cast(object, type("L", (), {"append_log_event": staticmethod(lambda e: None)})()),
        catalog_loader=loader,
        data_dir="/tmp/acp-data",
        event_bus=cast(object, event_bus),
    )
    return runtime, store, event_bus


def _acp_catalog(*, env_allowlist: list[str] | None = None, command: str = "acp-fake") -> RuntimeCatalog:
    return RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-local",
                label="ACP Local",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(
                    command=command,
                    args=["--stdio"],
                    env_allowlist=env_allowlist or [],
                    permission_timeout_s=30,
                    model_config_id="model",
                ),
            )
        ]
    )


def test_build_env_missing_allowlisted_var_rejects_launch(monkeypatch) -> None:
    runtime, _store, _bus = _make_runtime(catalog=_acp_catalog(env_allowlist=["ACP_TOKEN"]))
    monkeypatch.delenv("ACP_TOKEN", raising=False)
    config, _ = runtime._load_acp_config_sync("acp-local")
    assert config is not None
    with pytest.raises(RuntimeError, match="allowlisted environment variables are not set"):
        runtime._build_env(config)


def test_build_env_layers_allowlisted_values_and_neither_stores_nor_leaks(monkeypatch) -> None:
    runtime, _store, _bus = _make_runtime(
        catalog=_acp_catalog(env_allowlist=["ACP_TOKEN", "ACP_DEBUG"])
    )
    monkeypatch.setenv("ACP_TOKEN", "super-secret-value")
    monkeypatch.setenv("ACP_DEBUG", "1")
    config, _ = runtime._load_acp_config_sync("acp-local")
    assert config is not None
    env = runtime._build_env(config)
    # Allowlisted host values are present in the child env...
    assert env["ACP_TOKEN"] == "super-secret-value"
    assert env["ACP_DEBUG"] == "1"
    # ...but the AcpRuntimeConfig itself never stores values (only names).
    assert config.env_allowlist == ["ACP_TOKEN", "ACP_DEBUG"]
    # The config object carries no value attribute to leak.
    assert not hasattr(config, "env_values")


def test_build_env_has_small_base_not_full_os_environ(monkeypatch) -> None:
    runtime, _store, _bus = _make_runtime(catalog=_acp_catalog())
    monkeypatch.setenv("ACP_TOKEN", "v")
    monkeypatch.setenv("SOME_UNRELATED_HOST_VAR", "should-not-leak")
    config, _ = runtime._load_acp_config_sync("acp-local")
    assert config is not None
    env = runtime._build_env(config)
    assert "SOME_UNRELATED_HOST_VAR" not in env
    # Base keys subset; PATH guaranteed.
    assert "PATH" in env


@pytest.mark.parametrize(
    "decision, expected",
    [
        ("accept", "allow_once"),
        ("approve", "allow_once"),
        ("acceptForSession", "allow_always"),
        ("accept_for_session", "allow_always"),
        ("decline", "reject_once"),
        ("reject", "reject_once"),
        ("decline_always", "reject_always"),
        ("reject_always", "reject_always"),
        ("cancel", "cancelled"),
        ("cancelled", "cancelled"),
        ("", "reject_once"),  # unknown -> fail closed
        ("nonsense", "reject_once"),
    ],
)
def test_map_decision_to_outcome(decision: str, expected: str) -> None:
    assert AcpProcessRuntime._map_decision_to_outcome(decision) == expected


def test_load_acp_config_returns_none_for_unknown_executor() -> None:
    runtime, _store, _bus = _make_runtime(catalog=_acp_catalog())
    config, executor = runtime._load_acp_config_sync("does-not-exist")
    assert config is None
    assert executor is None


def test_load_acp_config_returns_none_when_acp_field_missing() -> None:
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-broken",
                label="Broken",
                enabled=True,
                executor_type="acp",
                acp=None,
            )
        ]
    )
    runtime, _store, _bus = _make_runtime(catalog=catalog)
    config, executor = runtime._load_acp_config_sync("acp-broken")
    assert config is None
    assert executor is not None
    assert executor.id == "acp-broken"


# ---------------------------------------------------------------------------
# RuntimeCatalogService ACP validation + resolution
# ---------------------------------------------------------------------------


def _acp_service() -> RuntimeCatalogService:
    """A RuntimeCatalogService whose store is never touched — the validation
    and resolution paths under test are pure functions over the catalog."""
    return RuntimeCatalogService(cast(object, None))


def test_validate_catalog_accepts_well_formed_acp_executor() -> None:
    service = _acp_service()
    catalog = _acp_catalog(env_allowlist=["ACP_TOKEN", "FOO_BAR"])
    # Should not raise.
    service.validate_catalog(catalog)


def test_validate_catalog_rejects_acp_without_config() -> None:
    service = _acp_service()
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-x", label="x", enabled=True, executor_type="acp", acp=None
            )
        ]
    )
    with pytest.raises(RuntimeCatalogValidationError, match="requires ACP launch configuration"):
        service.validate_catalog(catalog)


def test_validate_catalog_rejects_acp_with_providers() -> None:
    service = _acp_service()
    catalog = _acp_catalog()
    catalog.executors[0].providers = []  # placeholder; set real provider below
    from app.domain.models import RuntimeProviderConfig

    catalog.executors[0].providers = [
        RuntimeProviderConfig(id="p", label="p", enabled=True, models=[])
    ]
    with pytest.raises(RuntimeCatalogValidationError, match="cannot define providers"):
        service.validate_catalog(catalog)


def test_validate_catalog_rejects_acp_with_http_credentials() -> None:
    service = _acp_service()
    catalog = _acp_catalog()
    catalog.executors[0].api_key = "sk-leak"
    with pytest.raises(RuntimeCatalogValidationError, match="cannot define HTTP credentials"):
        service.validate_catalog(catalog)


def test_validate_catalog_rejects_acp_with_invalid_env_name() -> None:
    service = _acp_service()
    catalog = _acp_catalog(env_allowlist=["9bad"])
    with pytest.raises(RuntimeCatalogValidationError, match="invalid environment name"):
        service.validate_catalog(catalog)


def test_validate_catalog_rejects_acp_with_duplicate_env_name() -> None:
    service = _acp_service()
    catalog = _acp_catalog(env_allowlist=["ACP_TOKEN", "ACP_TOKEN"])
    with pytest.raises(RuntimeCatalogValidationError, match="repeats environment name"):
        service.validate_catalog(catalog)


def test_validate_catalog_rejects_acp_as_conductor_llm() -> None:
    service = _acp_service()
    catalog = _acp_catalog()
    catalog.conductor_llm.executor_id = "acp-local"
    with pytest.raises(RuntimeCatalogValidationError, match="ACP executors cannot be used as the Conductor LLM"):
        service.validate_catalog(catalog)


def test_resolve_effective_config_acp_branch() -> None:
    service = _acp_service()
    catalog = _acp_catalog()
    catalog.executors[0].default_model = "acp-default"
    executor, provider, model, env_overrides, executor_type = service.resolve_effective_config(
        catalog, "acp-local", provider=None, model=None
    )
    assert executor == "acp-local"
    assert provider == ""
    assert model == "acp-default"
    assert env_overrides is None
    assert executor_type == "acp"


def test_resolve_effective_config_acp_rejects_provider() -> None:
    service = _acp_service()
    catalog = _acp_catalog()
    with pytest.raises(RuntimeCatalogValidationError, match="does not support providers"):
        service.resolve_effective_config(
            catalog, "acp-local", provider="anthropic", model=None
        )


# ---------------------------------------------------------------------------
# End-to-end fake ACP subprocess
# ---------------------------------------------------------------------------

_E2E_ACP_SERVER_SRC = textwrap.dedent(
    """
    import json
    import sys

    def send(msg):
        sys.stdout.write(json.dumps(msg) + "\\n")
        sys.stdout.flush()

    def main():
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            method = msg.get("method")
            mid = msg.get("id")
            if method == "initialize":
                send({"jsonrpc": "2.0", "id": mid,
                      "result": {"protocolVersion": "1"}})
            elif method == "initialized":
                continue
            elif method == "session/new":
                send({"jsonrpc": "2.0", "id": mid,
                      "result": {"sessionId": "e2e-sess",
                                 "configOptions": [{"id": "model", "kind": "string"}]}})
            elif method == "session/set_config_option":
                send({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "session/prompt":
                # thought + tool + assistant message
                send({"jsonrpc": "2.0", "method": "session/update",
                      "params": {"update": {"kind": "thought", "thought": "planning"}}})
                send({"jsonrpc": "2.0", "method": "session/update",
                      "params": {"update": {"kind": "tool", "id": "tu-1",
                                            "name": "write_file", "state": "completed"}}})
                send({"jsonrpc": "2.0", "method": "session/update",
                      "params": {"update": {"kind": "message", "role": "assistant",
                                            "content": [{"type": "text", "text": "Done: hello"}]}}})
                send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn"}})
            elif method == "session/cancel":
                continue
            else:
                send({"jsonrpc": "2.0", "id": mid,
                      "error": {"code": -32601, "message": "method not found"}})

    main()
    """
)


def _write_e2e_server(tmp_path: Path) -> Path:
    server_path = tmp_path / "fake_acp_server.py"
    server_path.write_text(_E2E_ACP_SERVER_SRC, encoding="utf-8")
    return server_path


@pytest.mark.asyncio
async def test_e2e_fake_acp_subprocess_full_turn(tmp_path, monkeypatch) -> None:
    """A fake ACP v1 subprocess proves initialize -> session/new -> model
    option -> session/prompt and produces persisted assistant output plus
    structured thought/tool events."""
    server_path = _write_e2e_server(tmp_path)
    monkeypatch.setenv("ACP_E2E_TOKEN", "e2e-secret")

    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-e2e",
                label="E2E",
                enabled=True,
                executor_type="acp",
                default_model="acp-model-x",
                acp=AcpRuntimeConfig(
                    command=sys.executable,
                    args=[str(server_path)],
                    env_allowlist=["ACP_E2E_TOKEN"],
                    permission_timeout_s=30,
                    model_config_id="model",
                ),
            )
        ]
    )

    task = CodexTask(
        id="e2e-task",
        session_id="ws-e2e",
        title="E2E",
        prompt="do the thing",
        executor="acp-e2e",
        status="running",
        last_execution_process_id="ep-e2e",
        issue_id="issue-e2e",  # forces the worktree-cwd guard
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-e2e", title="ws", cwd=str(tmp_path))

    runtime, store, event_bus = _make_runtime(
        catalog=catalog, task=task, workspace=workspace
    )

    status = await runtime.write_input_async(
        workspace_id="ws-e2e",
        input_text="do the thing\n",
        wait=True,
        task_id="e2e-task",
        executor="acp",
        model="acp-model-x",
        cwd=str(tmp_path),
    )

    assert status == "done"
    # The ACP session id is persisted on the task only, never on workspace
    # claude_thread_id/thread_id.
    saved = store.saved_tasks[-1]
    assert saved.resume_session_id == "e2e-sess"
    assert workspace.thread_id is None
    assert workspace.claude_thread_id is None
    # Assistant output persisted as task.result.
    assert saved.result is not None
    assert "Done: hello" in saved.result
    assert saved.status == "done"
    # Structured thought/tool events flowed into the event bus as log events.
    log_streams = [str(e.get("stream")) for e in event_bus.events if e.get("type") == "log"]
    assert "thinking" in log_streams
    assert "tool_use" in log_streams
    # The allowlisted env value was never persisted anywhere in events.
    assert "e2e-secret" not in json.dumps(event_bus.events)


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_protocol_version_mismatch_fails_task(tmp_path) -> None:
    """A server that returns a mismatched protocolVersion fails the task and
    terminalizes its ExecutionProcess."""
    bad_server = tmp_path / "bad_acp_server.py"
    bad_server.write_text(
        textwrap.dedent(
            """
            import json, sys
            def send(m):
                sys.stdout.write(json.dumps(m) + "\\n"); sys.stdout.flush()
            for line in sys.stdin:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("method") == "initialize":
                    send({"jsonrpc": "2.0", "id": msg.get("id"),
                          "result": {"protocolVersion": "999"}})
            """
        ),
        encoding="utf-8",
    )

    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-bad",
                label="Bad",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(command=sys.executable, args=[str(bad_server)]),
            )
        ]
    )
    task = CodexTask(
        id="bad-task",
        session_id="ws-bad",
        title="bad",
        prompt="hi",
        executor="acp-bad",
        status="running",
        last_execution_process_id="ep-bad",
        issue_id="issue-bad",
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-bad", title="ws", cwd=str(tmp_path))
    runtime, store, _bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)

    status = await runtime.write_input_async(
        workspace_id="ws-bad",
        input_text="hi\n",
        wait=True,
        task_id="bad-task",
        executor="acp",
        cwd=str(tmp_path),
    )
    assert status == "failed"
    saved = store.saved_tasks[-1]
    assert saved.status == "failed"
    # ExecutionProcess terminalized.
    assert ("ep-bad", "Failed") in store.process_status_updates or any(
        s in ("Failed", "Killed") for _pid, s in store.process_status_updates
    )


@pytest.mark.asyncio
async def test_e2e_process_exit_before_handshake_fails_task(tmp_path) -> None:
    """A server that exits immediately must fail the task, not hang the full
    turn budget."""
    exit_server = tmp_path / "exit_acp_server.py"
    exit_server.write_text("import sys; sys.exit(7)\n", encoding="utf-8")

    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-exit",
                label="Exit",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(command=sys.executable, args=[str(exit_server)]),
            )
        ]
    )
    task = CodexTask(
        id="exit-task",
        session_id="ws-exit",
        title="exit",
        prompt="hi",
        executor="acp-exit",
        status="running",
        last_execution_process_id="ep-exit",
        issue_id="issue-exit",
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-exit", title="ws", cwd=str(tmp_path))
    runtime, store, _bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)

    status = await runtime.write_input_async(
        workspace_id="ws-exit",
        input_text="hi\n",
        wait=True,
        task_id="exit-task",
        executor="acp",
        cwd=str(tmp_path),
    )
    assert status == "failed"
    saved = store.saved_tasks[-1]
    assert saved.status == "failed"


@pytest.mark.asyncio
async def test_e2e_missing_allowlisted_env_rejects_launch(tmp_path, monkeypatch) -> None:
    """A missing allowlisted env var must reject launch before spawning."""
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-missing",
                label="Missing",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(
                    command=sys.executable,
                    args=["--version"],
                    env_allowlist=["ACP_REQUIRED_BUT_UNSET"],
                ),
            )
        ]
    )
    task = CodexTask(
        id="missing-env-task",
        session_id="ws-missing",
        title="missing",
        prompt="hi",
        executor="acp-missing",
        status="running",
        last_execution_process_id="ep-missing",
        issue_id="issue-missing",
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-missing", title="ws", cwd=str(tmp_path))
    runtime, _store, _bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)
    monkeypatch.delenv("ACP_REQUIRED_BUT_UNSET", raising=False)

    # write_input_async should propagate the RuntimeError from _build_env.
    with pytest.raises(RuntimeError, match="allowlisted environment variables are not set"):
        await runtime.write_input_async(
            workspace_id="ws-missing",
            input_text="hi\n",
            wait=True,
            task_id="missing-env-task",
            executor="acp",
            cwd=str(tmp_path),
        )


@pytest.mark.asyncio
async def test_issue_task_without_worktree_cwd_is_refused(tmp_path) -> None:
    """An issue task with no worktree cwd must refuse to run in the main repo."""
    catalog = _acp_catalog()
    task = CodexTask(
        id="no-cwd-task",
        session_id="ws-nocwd",
        title="nocwd",
        prompt="hi",
        executor="acp-local",
        status="running",
        last_execution_process_id="ep-nocwd",
        issue_id="issue-nocwd",  # triggers the worktree-cwd guard
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-nocwd", title="ws", cwd=str(tmp_path))
    runtime, _store, _bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)

    with pytest.raises(ValueError, match="no worktree cwd"):
        await runtime.write_input_async(
            workspace_id="ws-nocwd",
            input_text="hi\n",
            wait=True,
            task_id="no-cwd-task",
            executor="acp",
            # cwd intentionally omitted
        )


# ---------------------------------------------------------------------------
# Extended e2e: permission approve/reject, permission timeout -> cancelled,
# task cancel sends session/cancel, prompt timeout, probe endpoint.
# A dedicated fake server covers scenarios the base e2e server does not.
# ---------------------------------------------------------------------------

# Env-driven fake server that can: gate session/prompt on a permission request
# (only replying after the permission is resolved), never reply to session/prompt
# (to exercise turn timeout), and record session/cancel + permission outcomes.
_PERMISSION_GATING_SERVER_SRC = textwrap.dedent(
    """
    import json
    import os
    import sys

    MODE = os.environ.get("ACP_TEST_MODE", "permission_gate")
    # permission_gate: send session/request_permission, block prompt response
    #   until the client resolves it, then complete end_turn.
    # no_reply: never reply to session/prompt (turn timeout).
    # cancel_record: reply to prompt only after seeing session/cancel.
    LOG = os.environ.get("ACP_TEST_LOG_FILE")
    _log_lines = []

    def _log(kind, payload):
        _log_lines.append(json.dumps({"kind": kind, "payload": payload}))
        if LOG:
            with open(LOG, "w") as f:
                f.write("\\n".join(_log_lines))

    def send(msg):
        sys.stdout.write(json.dumps(msg) + "\\n")
        sys.stdout.flush()

    pending_prompt_id = None      # the original session/prompt id we owe a reply to
    pending_permission_id = None  # the id we used for the server-initiated permission request
    permission_resolved = False
    cancel_seen = False

    def main():
        global pending_prompt_id, pending_permission_id, permission_resolved, cancel_seen
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            method = msg.get("method")
            mid = msg.get("id")
            if method == "initialize":
                send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "1"}})
            elif method == "initialized":
                continue
            elif method == "session/new":
                send({"jsonrpc": "2.0", "id": mid, "result": {"sessionId": "perm-sess"}})
            elif method == "session/set_config_option":
                send({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "session/prompt":
                if MODE == "no_reply":
                    _log("prompt_no_reply", {"id": mid})
                    continue
                if MODE == "permission_gate":
                    pending_prompt_id = mid
                    pending_permission_id = "perm-" + str(mid)
                    send({"jsonrpc": "2.0", "id": pending_permission_id,
                          "method": "session/request_permission",
                          "params": {"options": [{"kind": "allow_once"},
                                                 {"kind": "reject_once"}]}})
                    # Do NOT reply to the prompt yet; the client must resolve
                    # the permission first. When the client sends the
                    # permission response, we complete the prompt below using
                    # the ORIGINAL prompt id.
                    _log("prompt_waiting_on_permission", {"id": mid})
                    continue
                if MODE == "cancel_record":
                    pending_prompt_id = mid
                    _log("prompt_waiting_on_cancel", {"id": mid})
                    continue
            elif method == "session/cancel":
                cancel_seen = True
                _log("cancel_seen", {})
                if MODE == "cancel_record" and pending_prompt_id is not None:
                    # Now that we saw the cancel, complete the original prompt.
                    send({"jsonrpc": "2.0", "id": pending_prompt_id,
                          "result": {"stopReason": "end_turn"}})
                    pending_prompt_id = None
                continue
            else:
                # A message with no method but with an id + result/error is the
                # client's response to our session/request_permission server
                # request. The id matches pending_permission_id.
                if mid is not None and ("result" in msg or "error" in msg):
                    _log("permission_response", {"id": mid,
                        "result": msg.get("result"),
                        "error": msg.get("error")})
                    if (MODE == "permission_gate"
                            and pending_permission_id is not None
                            and str(mid) == str(pending_permission_id)
                            and pending_prompt_id is not None):
                        permission_resolved = True
                        # Complete the ORIGINAL prompt — use its id, not the
                        # permission request id, so the client matches the
                        # response to its session/prompt call.
                        send({"jsonrpc": "2.0", "id": pending_prompt_id,
                              "result": {"stopReason": "end_turn"}})
                        pending_prompt_id = None
                        pending_permission_id = None
                else:
                    send({"jsonrpc": "2.0", "id": mid,
                          "error": {"code": -32601, "message": "method not found"}})

    main()
    """
)


def _write_permission_server(tmp_path: Path, mode: str, log_file: Path | None = None) -> Path:
    server_path = tmp_path / "fake_acp_perm_server.py"
    src = _PERMISSION_GATING_SERVER_SRC
    server_path.write_text(src, encoding="utf-8")
    return server_path


def _make_permission_catalog(tmp_path: Path, server_path: Path, *, permission_timeout_s: float) -> RuntimeCatalog:
    return RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-perm",
                label="Perm",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(
                    command=sys.executable,
                    args=[str(server_path)],
                    env_allowlist=["ACP_E2E_TOKEN"],
                    permission_timeout_s=permission_timeout_s,
                    model_config_id=None,
                ),
            )
        ]
    )


@pytest.mark.asyncio
async def test_e2e_permission_approve_resolves_and_completes(tmp_path, monkeypatch) -> None:
    """A session/request_permission during session/prompt is surfaced as an
    approval_required event; resolving it with 'accept' maps to allow_once and
    the turn completes with end_turn."""
    monkeypatch.setenv("ACP_E2E_TOKEN", "perm-secret")
    server_path = _write_permission_server(tmp_path, "permission_gate")
    catalog = _make_permission_catalog(tmp_path, server_path, permission_timeout_s=30)
    task = CodexTask(
        id="perm-task",
        session_id="ws-perm",
        title="perm",
        prompt="hi",
        executor="acp-perm",
        status="running",
        last_execution_process_id="ep-perm",
        issue_id="issue-perm",
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-perm", title="ws", cwd=str(tmp_path))
    runtime, store, event_bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)

    # Run the turn in a background task so we can resolve the permission
    # while write_input_async is blocked on it.
    turn_task = asyncio.create_task(
        runtime.write_input_async(
            workspace_id="ws-perm",
            input_text="hi\n",
            wait=True,
            task_id="perm-task",
            executor="acp",
            cwd=str(tmp_path),
        )
    )

    # Wait for the approval_required event to surface.
    item_id = await _wait_for_approval(event_bus, timeout=10.0)
    assert item_id is not None, "approval_required event was not emitted"

    # Accept the permission -> maps to allow_once.
    resolved = await runtime.resolve_approval(item_id, "accept")
    assert resolved is True

    status = await asyncio.wait_for(turn_task, timeout=15.0)
    assert status == "done"
    saved = store.saved_tasks[-1]
    assert saved.status == "done"
    # approval_resolved event recorded with the mapped outcome.
    resolved_events = [e for e in event_bus.events if e.get("type") == "approval_resolved"]
    assert resolved_events, "approval_resolved event missing"
    assert resolved_events[-1].get("outcome") == "allow_once"
    # Secret never leaked.
    assert "perm-secret" not in json.dumps(event_bus.events)


@pytest.mark.asyncio
async def test_e2e_permission_reject_maps_to_reject_once(tmp_path, monkeypatch) -> None:
    """A 'decline' decision maps to reject_once and resolves the approval."""
    monkeypatch.setenv("ACP_E2E_TOKEN", "perm-secret")
    server_path = _write_permission_server(tmp_path, "permission_gate")
    catalog = _make_permission_catalog(tmp_path, server_path, permission_timeout_s=30)
    task = CodexTask(
        id="perm-task",
        session_id="ws-perm",
        title="perm",
        prompt="hi",
        executor="acp-perm",
        status="running",
        last_execution_process_id="ep-perm",
        issue_id="issue-perm",
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-perm", title="ws", cwd=str(tmp_path))
    runtime, _store, event_bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)

    turn_task = asyncio.create_task(
        runtime.write_input_async(
            workspace_id="ws-perm",
            input_text="hi\n",
            wait=True,
            task_id="perm-task",
            executor="acp",
            cwd=str(tmp_path),
        )
    )
    item_id = await _wait_for_approval(event_bus, timeout=10.0)
    assert item_id is not None

    resolved = await runtime.resolve_approval(item_id, "decline")
    assert resolved is True

    await asyncio.wait_for(turn_task, timeout=15.0)
    resolved_events = [e for e in event_bus.events if e.get("type") == "approval_resolved"]
    assert resolved_events[-1].get("outcome") == "reject_once"


@pytest.mark.asyncio
async def test_e2e_permission_timeout_resolves_as_cancelled(tmp_path, monkeypatch) -> None:
    """An unresolved permission times out (per config.permission_timeout_s) and
    is resolved as cancelled (fail-closed)."""
    monkeypatch.setenv("ACP_E2E_TOKEN", "perm-secret")
    server_path = _write_permission_server(tmp_path, "permission_gate")
    # 1s timeout so the test stays fast.
    catalog = _make_permission_catalog(tmp_path, server_path, permission_timeout_s=1.0)
    task = CodexTask(
        id="perm-timeout-task",
        session_id="ws-pt",
        title="pt",
        prompt="hi",
        executor="acp-perm",
        status="running",
        last_execution_process_id="ep-pt",
        issue_id="issue-pt",
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-pt", title="ws", cwd=str(tmp_path))
    runtime, _store, event_bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)

    turn_task = asyncio.create_task(
        runtime.write_input_async(
            workspace_id="ws-pt",
            input_text="hi\n",
            wait=True,
            task_id="perm-timeout-task",
            executor="acp",
            cwd=str(tmp_path),
        )
    )
    item_id = await _wait_for_approval(event_bus, timeout=10.0)
    assert item_id is not None
    # Do NOT resolve the permission — let it time out.

    # Wait for the timeout-driven cancelled resolution.
    cancelled = await _wait_for_event(
        event_bus,
        lambda e: e.get("type") == "approval_resolved" and e.get("decision") == "cancelled",
        timeout=10.0,
    )
    assert cancelled, "permission did not time out to cancelled"
    # The pending approval is cleared after timeout.
    assert item_id not in runtime.get_pending_approvals()
    # Clean up the still-blocked turn.
    turn_task.cancel()
    with contextlib_suppress():
        await turn_task
    await runtime.terminate_task("perm-timeout-task")


@pytest.mark.asyncio
async def test_e2e_cancel_sends_session_cancel_and_resolves_permissions(tmp_path, monkeypatch) -> None:
    """Task cancellation sends session/cancel and resolves outstanding
    permissions as cancelled, then terminates the process tree."""
    monkeypatch.setenv("ACP_E2E_TOKEN", "perm-secret")
    server_path = _write_permission_server(tmp_path, "permission_gate")
    catalog = _make_permission_catalog(tmp_path, server_path, permission_timeout_s=60)
    task = CodexTask(
        id="cancel-task",
        session_id="ws-cancel",
        title="cancel",
        prompt="hi",
        executor="acp-perm",
        status="running",
        last_execution_process_id="ep-cancel",
        issue_id="issue-cancel",
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-cancel", title="ws", cwd=str(tmp_path))
    runtime, _store, event_bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)

    turn_task = asyncio.create_task(
        runtime.write_input_async(
            workspace_id="ws-cancel",
            input_text="hi\n",
            wait=True,
            task_id="cancel-task",
            executor="acp",
            cwd=str(tmp_path),
        )
    )
    item_id = await _wait_for_approval(event_bus, timeout=10.0)
    assert item_id is not None
    assert item_id in runtime.get_pending_approvals()

    # Cancel the task while the permission is pending.
    await runtime.terminate_task("cancel-task")

    # Outstanding permission resolved as cancelled.
    assert item_id not in runtime.get_pending_approvals()
    resolved = [e for e in event_bus.events if e.get("type") == "approval_resolved"]
    # Either the timeout or the cancel path resolved it as cancelled.
    assert any(r.get("decision") == "cancelled" for r in resolved), (
        "outstanding permission was not resolved as cancelled on cancel"
    )

    turn_task.cancel()
    with contextlib_suppress():
        await turn_task


@pytest.mark.asyncio
async def test_e2e_prompt_timeout_fails_task(tmp_path, monkeypatch) -> None:
    """A server that never replies to session/prompt exceeds the turn timeout
    and the task fails (fail-closed)."""
    monkeypatch.setenv("ACP_E2E_TOKEN", "perm-secret")
    server_path = _write_permission_server(tmp_path, "no_reply")
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-noreply",
                label="NoReply",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(
                    command=sys.executable,
                    args=[str(server_path)],
                    env_allowlist=["ACP_E2E_TOKEN"],
                    permission_timeout_s=30,
                    model_config_id=None,
                ),
            )
        ]
    )
    # Force a short turn timeout via env so the test stays fast.
    monkeypatch.setenv("ACP_TURN_TIMEOUT_S", "2")
    task = CodexTask(
        id="noreply-task",
        session_id="ws-nr",
        title="nr",
        prompt="hi",
        executor="acp-noreply",
        status="running",
        last_execution_process_id="ep-nr",
        issue_id="issue-nr",
        git_worktree_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(id="ws-nr", title="ws", cwd=str(tmp_path))
    runtime, store, _event_bus = _make_runtime(catalog=catalog, task=task, workspace=workspace)

    status = await runtime.write_input_async(
        workspace_id="ws-nr",
        input_text="hi\n",
        wait=True,
        task_id="noreply-task",
        executor="acp",
        cwd=str(tmp_path),
    )
    # Turn timeout surfaces as 'timeout' (or 'failed'); neither is 'done'.
    assert status != "done"
    assert status in ("timeout", "failed")
    saved = store.saved_tasks[-1]
    assert saved.status in ("failed", "timeout")
    assert ("ep-nr", "Killed") in store.process_status_updates or saved.status == "failed"


@pytest.mark.asyncio
async def test_probe_connectivity_success(tmp_path, monkeypatch) -> None:
    """probe_connectivity runs a real initialize handshake and reports success
    with latency, never returning env values."""
    monkeypatch.setenv("ACP_E2E_TOKEN", "probe-secret")
    server_path = _write_e2e_server(tmp_path)
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-probe",
                label="Probe",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(
                    command=sys.executable,
                    args=[str(server_path)],
                    env_allowlist=["ACP_E2E_TOKEN"],
                    permission_timeout_s=30,
                    model_config_id=None,
                ),
            )
        ]
    )
    runtime, _store, _bus = _make_runtime(catalog=catalog)
    success, error, latency_ms = await runtime.probe_connectivity("acp-probe")
    assert success is True
    assert error == ""
    assert latency_ms >= 0
    # Env value never surfaced in error or anywhere.
    assert "probe-secret" not in str(error)


@pytest.mark.asyncio
async def test_probe_connectivity_missing_env_fails(tmp_path, monkeypatch) -> None:
    """probe_connectivity refuses to launch when an allowlisted env var is
    missing, reporting an actionable error without hanging."""
    server_path = _write_e2e_server(tmp_path)
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-probe-missing",
                label="ProbeMissing",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(
                    command=sys.executable,
                    args=[str(server_path)],
                    env_allowlist=["ACP_PROBE_REQUIRED_BUT_UNSET"],
                    permission_timeout_s=30,
                    model_config_id=None,
                ),
            )
        ]
    )
    monkeypatch.delenv("ACP_PROBE_REQUIRED_BUT_UNSET", raising=False)
    runtime, _store, _bus = _make_runtime(catalog=catalog)
    success, error, latency_ms = await runtime.probe_connectivity("acp-probe-missing")
    assert success is False
    assert "ACP_PROBE_REQUIRED_BUT_UNSET" in error
    assert latency_ms == 0


@pytest.mark.asyncio
async def test_probe_connectivity_protocol_mismatch_fails(tmp_path, monkeypatch) -> None:
    """probe_connectivity reports failure when the agent returns a mismatched
    protocol version."""
    # The fake server reads ACP_TEST_PROTOCOL_VERSION from its env. Because the
    # runtime only forwards allowlisted env vars to the child, the variable
    # must be in env_allowlist (and set in the host env) for the server to see
    # it. ACP_TEST_STOP_REASON is included so the server does not gate on it.
    monkeypatch.setenv("ACP_E2E_TOKEN", "probe-secret")
    monkeypatch.setenv("ACP_TEST_PROTOCOL_VERSION", "999")
    server_path = _write_fake_server(tmp_path)
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="acp-probe-mismatch",
                label="ProbeMismatch",
                enabled=True,
                executor_type="acp",
                acp=AcpRuntimeConfig(
                    command=sys.executable,
                    args=[str(server_path)],
                    env_allowlist=["ACP_E2E_TOKEN", "ACP_TEST_PROTOCOL_VERSION"],
                    permission_timeout_s=30,
                    model_config_id=None,
                ),
            )
        ]
    )
    runtime, _store, _bus = _make_runtime(catalog=catalog)
    success, error, _latency = await runtime.probe_connectivity("acp-probe-mismatch")
    assert success is False
    assert "protocol" in error.lower() or "mismatch" in error.lower()


# ---------------------------------------------------------------------------
# Helpers for the extended e2e tests.
# ---------------------------------------------------------------------------


async def _wait_for_approval(event_bus: _RecordingEventBus, *, timeout: float) -> str | None:
    """Return the item_id of the first approval_required event, or None."""
    return await _wait_for_event(
        event_bus,
        lambda e: e.get("type") == "approval_required" and e.get("item_id"),
        timeout=timeout,
        extractor=lambda e: str(e.get("item_id")),
    )


async def _wait_for_event(
    event_bus: _RecordingEventBus,
    predicate,
    *,
    timeout: float,
    extractor=None,
):
    """Poll the event bus until predicate matches an event (or timeout)."""
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        for e in event_bus.events:
            try:
                if predicate(e):
                    return extractor(e) if extractor else True
            except Exception:
                continue
        await asyncio.sleep(0.05)
    return None


def contextlib_suppress():
    from contextlib import suppress

    return suppress(asyncio.CancelledError, Exception)

