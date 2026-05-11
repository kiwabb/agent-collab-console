"""Tests for token-level message streaming (P1).

The Claude CLI emits multiple "assistant" type messages during a single turn
(via --include-partial-messages), each carrying the growing content array.
Backend must compute the increment vs. last emission and broadcast a
"message_delta" event so the frontend can render a typewriter effect."""
from datetime import datetime

import pytest

from app.application.process_runtime_common import AsyncProcessEntry, BaseProcessRuntime
from app.domain.models import CodexSession, CodexTask, ExecutionProcess


class _EventBusSpy:
    def __init__(self):
        self.events: list[dict] = []

    async def append(self, event: dict):
        self.events.append(event)


def _make_entry(task_id: str) -> AsyncProcessEntry:
    return AsyncProcessEntry(
        proc=None,  # type: ignore[arg-type]
        output_task=None,
        alive=True,
        session_id="ws-1",
        task_id=task_id,
        executor="claude",
        cwd="/tmp",
        resume_session_id=None,
    )


async def _seed_db(tmp_path, ep_id="ep-stream-1"):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db = AsyncSQLiteStore(str(tmp_path / "db.sqlite"))
    now = datetime.now()
    session = CodexSession(id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now)
    await db.save_codex_session(session)
    task = CodexTask(
        id="task-1", session_id="ws-1", phase="requirements", title="t", prompt="p",
        role="product_manager", executor="claude", status="running",
        workspace_path=str(tmp_path), last_execution_process_id=ep_id,
        created_at=now, updated_at=now,
    )
    await db.save_codex_task(task)
    ep = ExecutionProcess(id=ep_id, task_id="task-1", session_id="ws-1",
                          status="Running", kind="initial", created_at=now, updated_at=now)
    await db.save_execution_process(ep)
    return db


@pytest.mark.asyncio
async def test_assistant_partials_emit_message_delta_events(tmp_path):
    """Three growing assistant messages → 3 message_delta events with incremental delta_text + monotonic seq."""
    db = await _seed_db(tmp_path)
    bus = _EventBusSpy()
    runtime = BaseProcessRuntime(codex_store=db, log_store=db, data_dir=str(tmp_path), event_bus=bus, refresh_task_result=None)
    entry = _make_entry("task-1")

    # Simulate 3 progressive partial-message lines from claude (--include-partial-messages)
    import json as _json

    async def _claude_assistant(text: str):
        line = _json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        await runtime._capture_on_reader("ws-1", line, entry, "task-1")

    await _claude_assistant("Hello")
    await _claude_assistant("Hello, world")
    await _claude_assistant("Hello, world!")

    deltas = [e for e in bus.events if e.get("type") == "message_delta"]
    assert len(deltas) == 3, f"Expected 3 deltas, got {len(deltas)}: {deltas}"
    assert deltas[0]["delta_text"] == "Hello"
    assert deltas[1]["delta_text"] == ", world"
    assert deltas[2]["delta_text"] == "!"
    seqs = [d["seq"] for d in deltas]
    assert seqs == sorted(seqs) and len(set(seqs)) == 3, f"seq must be strictly monotonic: {seqs}"
    for d in deltas:
        assert d["execution_process_id"] == "ep-stream-1"
        assert d["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_assistant_unchanged_text_emits_no_delta(tmp_path):
    """If the same text is emitted twice (idempotent partial), no second delta."""
    db = await _seed_db(tmp_path)
    bus = _EventBusSpy()
    runtime = BaseProcessRuntime(codex_store=db, log_store=db, data_dir=str(tmp_path), event_bus=bus, refresh_task_result=None)
    entry = _make_entry("task-1")

    import json as _json
    async def _emit(text):
        line = _json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        await runtime._capture_on_reader("ws-1", line, entry, "task-1")

    await _emit("Hello")
    await _emit("Hello")
    await _emit("Hello")

    deltas = [e for e in bus.events if e.get("type") == "message_delta"]
    assert len(deltas) == 1
    assert deltas[0]["delta_text"] == "Hello"


@pytest.mark.asyncio
async def test_assistant_non_prefix_change_emits_full_text_as_delta(tmp_path):
    """If new text doesn't start with previous (rare revision), emit full new text as delta."""
    db = await _seed_db(tmp_path)
    bus = _EventBusSpy()
    runtime = BaseProcessRuntime(codex_store=db, log_store=db, data_dir=str(tmp_path), event_bus=bus, refresh_task_result=None)
    entry = _make_entry("task-1")

    import json as _json
    async def _emit(text):
        line = _json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        await runtime._capture_on_reader("ws-1", line, entry, "task-1")

    await _emit("Hello there")
    await _emit("Goodbye world")

    deltas = [e for e in bus.events if e.get("type") == "message_delta"]
    assert len(deltas) == 2
    assert deltas[0]["delta_text"] == "Hello there"
    # Second emission is not a prefix-extension; full text becomes the delta
    assert deltas[1]["delta_text"] == "Goodbye world"


@pytest.mark.asyncio
async def test_message_delta_event_includes_execution_process_id_from_task(tmp_path):
    """The event carries execution_process_id resolved from task.last_execution_process_id at emit time."""
    db = await _seed_db(tmp_path, ep_id="ep-custom-42")
    bus = _EventBusSpy()
    runtime = BaseProcessRuntime(codex_store=db, log_store=db, data_dir=str(tmp_path), event_bus=bus, refresh_task_result=None)
    entry = _make_entry("task-1")

    import json as _json
    line = _json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}})
    await runtime._capture_on_reader("ws-1", line, entry, "task-1")

    deltas = [e for e in bus.events if e.get("type") == "message_delta"]
    assert len(deltas) == 1
    assert deltas[0]["execution_process_id"] == "ep-custom-42"


# ---------------------------------------------------------------------------
# event_bus / message_stream_manager routing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Codex app-server: item.delta / item/delta / item.updated notifications →
# message_delta events (same protocol as the Claude path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_item_delta_emits_message_delta_events(tmp_path):
    """When the Codex notification callback receives item.delta / item.updated for
    an agent_message item, it must compute the text increment and broadcast
    message_delta events (same as the Claude path)."""
    db = await _seed_db(tmp_path, ep_id="ep-codex-1")
    bus = _EventBusSpy()

    from app.application.codex_app_server_runtime import CodexAppServerRuntime
    # CodexAppServerRuntime requires several dependencies; we build a minimal
    # instance by constructing manually and only exercising the notification path.
    runtime = CodexAppServerRuntime.__new__(CodexAppServerRuntime)
    runtime.codex_store = db
    runtime._log_store = db
    runtime._event_bus = bus
    runtime._processes = {}
    runtime.help_orchestrator = None
    runtime._mock_manager_cls = None
    runtime._data_dir = str(tmp_path)
    runtime.refresh_task_result = None

    entry = AsyncProcessEntry(
        proc=None,  # type: ignore[arg-type]
        output_task=None,
        alive=True,
        session_id="ws-1",
        task_id="task-1",
        executor="codex",
        cwd=str(tmp_path),
        resume_session_id=None,
    )
    runtime._processes["task-1"] = entry

    callback = runtime._make_app_server_notification_callback("ws-1", "task-1")

    # Three progressive item.delta notifications carrying growing assistant text
    await callback("item.delta", {"item": {"type": "agent_message", "text": "Hello"}})
    await callback("item/delta", {"item": {"type": "agent_message", "text": "Hello, world"}})
    await callback("item.updated", {"item": {"type": "agent_message", "text": "Hello, world!"}})

    deltas = [e for e in bus.events if e.get("type") == "message_delta"]
    assert len(deltas) == 3
    assert deltas[0]["delta_text"] == "Hello"
    assert deltas[1]["delta_text"] == ", world"
    assert deltas[2]["delta_text"] == "!"
    seqs = [d["seq"] for d in deltas]
    assert seqs == sorted(seqs) and len(set(seqs)) == 3
    for d in deltas:
        assert d["execution_process_id"] == "ep-codex-1"
        assert d["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_codex_item_delta_ignored_for_non_agent_message_item(tmp_path):
    """tool_call, command_execution, etc. should not produce message_delta events."""
    db = await _seed_db(tmp_path, ep_id="ep-codex-2")
    bus = _EventBusSpy()
    from app.application.codex_app_server_runtime import CodexAppServerRuntime
    runtime = CodexAppServerRuntime.__new__(CodexAppServerRuntime)
    runtime.codex_store = db
    runtime._log_store = db
    runtime._event_bus = bus
    runtime._processes = {}
    runtime.help_orchestrator = None
    runtime._data_dir = str(tmp_path)
    runtime.refresh_task_result = None

    entry = AsyncProcessEntry(
        proc=None, output_task=None, alive=True, session_id="ws-1",  # type: ignore[arg-type]
        task_id="task-1", executor="codex", cwd=str(tmp_path), resume_session_id=None,
    )
    runtime._processes["task-1"] = entry

    callback = runtime._make_app_server_notification_callback("ws-1", "task-1")
    await callback("item.delta", {"item": {"type": "tool_use", "text": "ignored"}})
    await callback("item.delta", {"item": {"type": "command_execution", "text": "ignored"}})

    deltas = [e for e in bus.events if e.get("type") == "message_delta"]
    assert deltas == []


@pytest.mark.asyncio
async def test_event_bus_routes_message_delta_to_message_stream_manager(monkeypatch):
    """When event_bus._broadcast_to_ws sees a message_delta event, it must call
    message_stream_manager.publish_delta(execution_process_id, delta_event_dict)."""
    from app.application import event_bus as event_bus_module
    from app.interfaces import codex_ws as codex_ws_module

    captured = []

    class _MgrStub:
        async def publish_delta(self, ep_id, event):
            captured.append((ep_id, event))
        async def publish_message(self, *a, **kw):
            pass
        async def publish_finished(self, *a, **kw):
            pass

    class _SnapMgrStub:
        async def add_message(self, *a, **kw):
            pass

    monkeypatch.setattr(codex_ws_module, "message_stream_manager", _MgrStub())
    # Also stub stream_manager to no-op so we don't fail on unrelated paths
    monkeypatch.setattr(codex_ws_module, "stream_manager", _SnapMgrStub())

    bus = event_bus_module.EventBus()
    event = {
        "type": "message_delta",
        "execution_process_id": "ep-x",
        "task_id": "task-1",
        "session_id": "ws-1",
        "seq": 7,
        "delta_text": "hello",
    }
    await bus._broadcast_to_ws(event)

    assert len(captured) == 1
    ep_id, fwd = captured[0]
    assert ep_id == "ep-x"
    assert fwd["delta_text"] == "hello"
    assert fwd["seq"] == 7
