"""Tests for token-level message streaming (P1).

The Claude CLI emits multiple "assistant" type messages during a single turn
(via --include-partial-messages), each carrying the growing content array.
Backend must compute the increment vs. last emission and broadcast a
"message_delta" event so the frontend can render a typewriter effect."""

from asyncio.subprocess import Process
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.codex_app_server_runtime import CodexAppServerRuntime
from app.application.process_runtime_common import (
    AsyncProcessEntry,
    BaseProcessRuntime,
    ProcessEntry,
)
from app.domain.models import CodexSession, CodexTask, ExecutionProcess


class _EventBusSpy:
    def __init__(self):
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)

    async def queue_log_event(self, event) -> None:
        return None


def _message_delta_sequences(deltas: list[dict[str, object]]) -> list[int]:
    seqs: list[int] = []
    for delta in deltas:
        seq = delta.get("seq")
        assert isinstance(seq, int)
        seqs.append(seq)
    return seqs


class _TestProcessRuntime(BaseProcessRuntime):
    def _owns_entry(self, entry: AsyncProcessEntry) -> bool:
        return True

    async def _cleanup_entry(
        self, workspace_id: str, entry: ProcessEntry | AsyncProcessEntry
    ) -> None:
        entry.alive = False


def _make_entry(task_id: str) -> AsyncProcessEntry:
    return AsyncProcessEntry(
        proc=cast(Process, None),
        output_task=None,
        alive=True,
        session_id="ws-1",
        task_id=task_id,
        executor="claude",
        cwd="/tmp",
        resume_session_id=None,
    )


async def _seed_db(tmp_path: Path, ep_id: str = "ep-stream-1") -> AsyncSQLiteStore:
    db = AsyncSQLiteStore(str(tmp_path / "db.sqlite"))
    now = datetime.now()
    session = CodexSession(
        id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now
    )
    await db.save_codex_session(session)
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        phase="requirements",
        title="t",
        prompt="p",
        role="product_manager",
        executor="claude",
        status="running",
        workspace_path=str(tmp_path),
        last_execution_process_id=ep_id,
        created_at=now,
        updated_at=now,
    )
    await db.save_codex_task(task)
    ep = ExecutionProcess(
        id=ep_id,
        task_id="task-1",
        session_id="ws-1",
        status="Running",
        kind="initial",
        created_at=now,
        updated_at=now,
    )
    await db.save_execution_process(ep)
    return db


def _make_codex_runtime_for_notifications(
    db: AsyncSQLiteStore, bus: _EventBusSpy, tmp_path: Path
) -> CodexAppServerRuntime:
    return CodexAppServerRuntime(
        codex_store=db,
        log_store=db,
        data_dir=str(tmp_path),
        event_bus=bus,
        refresh_task_result=None,
    )


@pytest.mark.asyncio
async def test_terminate_task_emits_complete_task_status_payload(tmp_path):
    db = await _seed_db(tmp_path, ep_id="ep-kill-1")
    try:
        bus = _EventBusSpy()
        runtime = _TestProcessRuntime(
            codex_store=db,
            log_store=db,
            data_dir=str(tmp_path),
            event_bus=bus,
            refresh_task_result=None,
        )
        runtime._processes["task-1"] = _make_entry("task-1")

        await runtime.terminate_task("task-1")

        event = [e for e in bus.events if e.get("type") == "task_status"][-1]
        assert event["task_id"] == "task-1"
        assert event["project_id"] is None
        assert event["issue_id"] is None
        assert event["workspace_id"] == "ws-1"
        assert event["session_id"] == "ws-1"
        assert event["role"] == "product_manager"
        assert event["task_kind"] == "normal"
        assert event["status"] == "failed"
        assert event["execution_process_id"] == "ep-kill-1"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_assistant_partials_emit_message_delta_events(tmp_path):
    """Three growing assistant messages → 3 message_delta events with incremental delta_text + monotonic seq."""
    db = await _seed_db(tmp_path)
    try:
        bus = _EventBusSpy()
        runtime = BaseProcessRuntime(
            codex_store=db,
            log_store=db,
            data_dir=str(tmp_path),
            event_bus=bus,
            refresh_task_result=None,
        )
        entry = _make_entry("task-1")

        # Simulate 3 progressive partial-message lines from claude (--include-partial-messages)
        import json as _json

        async def _claude_assistant(text: str):
            line = _json.dumps(
                {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
            )
            await runtime._capture_on_reader("ws-1", line, entry, "task-1")

        await _claude_assistant("Hello")
        await _claude_assistant("Hello, world")
        await _claude_assistant("Hello, world!")

        deltas = [e for e in bus.events if e.get("type") == "message_delta"]
        assert len(deltas) == 3, f"Expected 3 deltas, got {len(deltas)}: {deltas}"
        assert deltas[0]["delta_text"] == "Hello"
        assert deltas[1]["delta_text"] == ", world"
        assert deltas[2]["delta_text"] == "!"
        seqs = _message_delta_sequences(deltas)
        assert seqs == sorted(seqs) and len(set(seqs)) == 3, (
            f"seq must be strictly monotonic: {seqs}"
        )
        for d in deltas:
            assert d["execution_process_id"] == "ep-stream-1"
            assert d["task_id"] == "task-1"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_assistant_unchanged_text_emits_no_delta(tmp_path):
    """If the same text is emitted twice (idempotent partial), no second delta."""
    db = await _seed_db(tmp_path)
    try:
        bus = _EventBusSpy()
        runtime = BaseProcessRuntime(
            codex_store=db,
            log_store=db,
            data_dir=str(tmp_path),
            event_bus=bus,
            refresh_task_result=None,
        )
        entry = _make_entry("task-1")

        import json as _json

        async def _emit(text):
            line = _json.dumps(
                {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
            )
            await runtime._capture_on_reader("ws-1", line, entry, "task-1")

        await _emit("Hello")
        await _emit("Hello")
        await _emit("Hello")

        deltas = [e for e in bus.events if e.get("type") == "message_delta"]
        assert len(deltas) == 1
        assert deltas[0]["delta_text"] == "Hello"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_assistant_non_prefix_change_emits_full_text_as_delta(tmp_path):
    """If new text doesn't start with previous (rare revision), emit full new text as delta."""
    db = await _seed_db(tmp_path)
    try:
        bus = _EventBusSpy()
        runtime = BaseProcessRuntime(
            codex_store=db,
            log_store=db,
            data_dir=str(tmp_path),
            event_bus=bus,
            refresh_task_result=None,
        )
        entry = _make_entry("task-1")

        import json as _json

        async def _emit(text):
            line = _json.dumps(
                {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
            )
            await runtime._capture_on_reader("ws-1", line, entry, "task-1")

        await _emit("Hello there")
        await _emit("Goodbye world")

        deltas = [e for e in bus.events if e.get("type") == "message_delta"]
        assert len(deltas) == 2
        assert deltas[0]["delta_text"] == "Hello there"
        # Second emission is not a prefix-extension; full text becomes the delta
        assert deltas[1]["delta_text"] == "Goodbye world"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_message_delta_event_includes_execution_process_id_from_task(tmp_path):
    """The event carries execution_process_id resolved from task.last_execution_process_id at emit time."""
    db = await _seed_db(tmp_path, ep_id="ep-custom-42")
    try:
        bus = _EventBusSpy()
        runtime = BaseProcessRuntime(
            codex_store=db,
            log_store=db,
            data_dir=str(tmp_path),
            event_bus=bus,
            refresh_task_result=None,
        )
        entry = _make_entry("task-1")

        import json as _json

        line = _json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}}
        )
        await runtime._capture_on_reader("ws-1", line, entry, "task-1")

        deltas = [e for e in bus.events if e.get("type") == "message_delta"]
        assert len(deltas) == 1
        assert deltas[0]["execution_process_id"] == "ep-custom-42"
    finally:
        await db.close()


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
    try:
        bus = _EventBusSpy()

        # CodexAppServerRuntime requires several dependencies; we build a minimal
        # instance by constructing manually and only exercising the notification path.
        runtime = _make_codex_runtime_for_notifications(db, bus, tmp_path)
        runtime._processes["task-1"] = _make_entry("task-1")

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
        seqs = _message_delta_sequences(deltas)
        assert seqs == sorted(seqs) and len(set(seqs)) == 3
        for d in deltas:
            assert d["execution_process_id"] == "ep-codex-1"
            assert d["task_id"] == "task-1"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_codex_item_delta_ignored_for_non_agent_message_item(tmp_path):
    """tool_call, command_execution, etc. should not produce message_delta events."""
    db = await _seed_db(tmp_path, ep_id="ep-codex-2")
    try:
        bus = _EventBusSpy()
        runtime = _make_codex_runtime_for_notifications(db, bus, tmp_path)
        runtime._processes["task-1"] = _make_entry("task-1")

        callback = runtime._make_app_server_notification_callback("ws-1", "task-1")
        await callback("item.delta", {"item": {"type": "tool_use", "text": "ignored"}})
        await callback("item.delta", {"item": {"type": "command_execution", "text": "ignored"}})

        deltas = [e for e in bus.events if e.get("type") == "message_delta"]
        assert deltas == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_codex_failed_turn_uses_turn_error_not_prior_final_answer(tmp_path):
    """If Codex emits a final_answer item before the turn later completes as
    failed, the task failure reason must come from the turn error payload
    instead of the previously captured assistant text."""
    db = await _seed_db(tmp_path, ep_id="ep-codex-failed-1")
    try:
        bus = _EventBusSpy()

        runtime = _make_codex_runtime_for_notifications(db, bus, tmp_path)
        runtime._processes["task-1"] = _make_entry("task-1")

        callback = runtime._make_app_server_notification_callback("ws-1", "task-1")

        await callback(
            "item.completed",
            {
                "item": {
                    "type": "agent_message",
                    "phase": "final_answer",
                    "text": '{"language":"zh-CN"}',
                }
            },
        )
        await callback(
            "turn.completed",
            {
                "status": "failed",
                "turn": {
                    "status": "failed",
                    "error": {
                        "message": "ProductManager 返回了无效的 PRD 格式",
                    },
                },
            },
        )

        task = await db.load_codex_task("task-1")
        assert task is not None
        assert task.status == "failed"
        assert task.result == "ProductManager 返回了无效的 PRD 格式"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_codex_error_turn_status_marks_task_failed(tmp_path):
    """Codex app-server failure aliases like status=error must not be persisted as done."""
    db = await _seed_db(tmp_path, ep_id="ep-codex-error-1")
    try:
        bus = _EventBusSpy()

        runtime = _make_codex_runtime_for_notifications(db, bus, tmp_path)
        runtime._processes["task-1"] = _make_entry("task-1")

        callback = runtime._make_app_server_notification_callback("ws-1", "task-1")

        await callback(
            "turn.completed",
            {
                "status": "error",
                "error": {"message": "app-server turn crashed"},
            },
        )

        task = await db.load_codex_task("task-1")
        assert task is not None
        assert task.status == "failed"
        assert task.result == "app-server turn crashed"
    finally:
        await db.close()


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


@pytest.mark.asyncio
async def test_event_bus_treats_error_task_status_as_terminal(monkeypatch):
    """Failure aliases must close streams and notify the workflow scheduler."""
    from app.application import event_bus as event_bus_module
    from app.interfaces import codex_ws as codex_ws_module

    finished: list[tuple[str, str]] = []
    scheduler_notifications: list[str] = []

    class _MessageMgrStub:
        async def publish_finished(self, ep_id):
            finished.append(("message", ep_id))

    class _RawLogMgrStub:
        async def publish_finished(self, ep_id):
            finished.append(("raw_log", ep_id))

    class _StreamMgrStub:
        async def update_task_status(self, *args, **kwargs):
            pass

    monkeypatch.setattr(codex_ws_module, "message_stream_manager", _MessageMgrStub())
    monkeypatch.setattr(codex_ws_module, "raw_log_stream_manager", _RawLogMgrStub())
    monkeypatch.setattr(codex_ws_module, "stream_manager", _StreamMgrStub())

    bus = event_bus_module.EventBus()

    async def _notify(task_id: str) -> None:
        scheduler_notifications.append(task_id)

    monkeypatch.setattr(bus, "_notify_workflow_scheduler", _notify)

    await bus._broadcast_to_ws(
        {
            "type": "task_status",
            "task_id": "task-1",
            "session_id": "ws-1",
            "status": "error",
            "execution_process_id": "ep-1",
        }
    )

    assert finished == [("message", "ep-1"), ("raw_log", "ep-1")]
    assert scheduler_notifications == ["task-1"]
