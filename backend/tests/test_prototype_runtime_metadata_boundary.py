from __future__ import annotations

import json
from asyncio.subprocess import Process
from datetime import datetime
from typing import cast

import pytest

from app.application.audit import record_event
from app.application.process_runtime_common import AsyncProcessEntry, BaseProcessRuntime
from app.domain.models import (
    AgentCallTrace,
    CodexSession,
    CodexTask,
    CodexTaskMessage,
    ExecutionProcess,
    HelpRequest,
    LogEvent,
)
from app.domain.ports import AuditSink

SENTINEL_PAYLOAD = '{"contractVersion":1,"message":"PROTOTYPE-SECRET"}'
SENTINEL_COMMAND = "echo 'PROTOTYPE-COMMAND-SECRET'"


def _null_process() -> Process:
    return cast(Process, None)


class _Store:
    def __init__(self, task: CodexTask) -> None:
        self.task = task
        self.load_task_calls = 0
        self.logs: list[LogEvent] = []
        self.messages: list[CodexTaskMessage] = []
        self.traces: list[AgentCallTrace] = []

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        self.load_task_calls += 1
        return self.task if task_id == self.task.id else None

    async def save_codex_task(self, task: CodexTask) -> None:
        self.task = task.model_copy(deep=True)

    async def load_execution_process(self, process_id: str) -> ExecutionProcess | None:
        return None

    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        return None

    async def update_execution_process_usage(
        self,
        process_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        total_cost_usd: float | None = None,
    ) -> None:
        return None

    async def append_log_event(self, event: LogEvent) -> None:
        self.logs.append(event)

    async def load_log_events(
        self,
        session_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 500,
        reverse: bool = False,
    ) -> list[LogEvent]:
        del limit
        rows = [
            event
            for event in self.logs
            if event.session_id == session_id
            and (task_id is None or event.task_id == task_id)
            and (execution_process_id is None or event.execution_process_id == execution_process_id)
        ]
        return list(reversed(rows)) if reverse else rows

    async def save_codex_task_message(self, message: CodexTaskMessage) -> None:
        self.messages.append(message)

    async def list_codex_task_messages(
        self,
        task_id: str,
        execution_process_id: str | None = None,
    ) -> list[CodexTaskMessage]:
        return [
            message
            for message in self.messages
            if message.task_id == task_id
            and (
                execution_process_id is None or message.execution_process_id == execution_process_id
            )
        ]

    async def save_agent_call_trace(self, trace: AgentCallTrace) -> None:
        self.traces.append(trace)

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return None

    async def save_codex_workspace(self, workspace: CodexSession) -> None:
        return None

    async def load_help_request(self, help_request_id: str) -> HelpRequest | None:
        return None


class _EventBus:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.events: list[dict[str, object]] = []

    async def queue_log_event(self, event: LogEvent) -> None:
        await self.store.append_log_event(event)

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)


class _Runtime(BaseProcessRuntime):
    def _owns_entry(self, entry: AsyncProcessEntry) -> bool:
        return True


def _task(*, task_kind: str) -> CodexTask:
    now = datetime.now()
    return CodexTask(
        id=f"task-{task_kind}",
        session_id="workspace-prototype",
        project_id="project-1",
        title=f"Generate {SENTINEL_PAYLOAD}",
        prompt=f"Submit a typed result without returning {SENTINEL_PAYLOAD}",
        role="prototype_ui_engineer" if task_kind == "generation_page" else "engineer",
        executor="claude",
        status="running",
        task_kind=task_kind,
        workspace_path="/tmp/workspace",
        last_execution_process_id=f"process-{task_kind}",
        trace_id=f"trace-{task_kind}",
        span_id=f"span-{task_kind}",
        created_at=now,
        updated_at=now,
    )


def _entry(task: CodexTask) -> AsyncProcessEntry:
    return AsyncProcessEntry(
        proc=_null_process(),
        output_task=None,
        alive=False,
        session_id=task.session_id,
        task_id=task.id,
        executor="claude",
        cwd="/tmp/workspace",
        resume_session_id=None,
    )


@pytest.mark.asyncio
async def test_ui_engineer_runtime_persists_complete_stream_and_terminal_result() -> None:
    task = _task(task_kind="generation_page")
    store = _Store(task)
    bus = _EventBus(store)
    runtime = _Runtime(codex_store=store, log_store=store, event_bus=bus)
    entry = _entry(task)
    assistant_frame = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": f"inspect {SENTINEL_PAYLOAD}"},
                    {
                        "type": "tool_use",
                        "id": "toolu-write-1",
                        "name": "Bash",
                        "input": {"command": SENTINEL_COMMAND, "payload": SENTINEL_PAYLOAD},
                    },
                    {"type": "text", "text": SENTINEL_PAYLOAD},
                ]
            },
        }
    )
    tool_result_frame = json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu-write-1",
                        "content": SENTINEL_PAYLOAD,
                        "is_error": True,
                    }
                ]
            },
        }
    )
    result_frame = json.dumps({"type": "result", "result": SENTINEL_PAYLOAD})

    for frame in (assistant_frame, tool_result_frame, result_frame):
        await runtime._capture_on_reader(task.session_id, frame, entry, task.id)
        await runtime._append_log(
            task.session_id,
            "stdout",
            frame,
            task.id,
            task_context=entry.task_context,
        )

    assert store.load_task_calls == 1
    assert entry.result_text == SENTINEL_PAYLOAD

    await runtime._mark_task_done(task.id, entry)

    assert store.task.status == "done"
    assert store.task.result == SENTINEL_PAYLOAD
    assert store.messages[-1].content == SENTINEL_PAYLOAD
    persisted_logs = "\n".join(event.content for event in store.logs)
    assert "PROTOTYPE-SECRET" in persisted_logs
    assert SENTINEL_COMMAND in persisted_logs

    trace = store.traces[-1]
    serialized_trace = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False)
    assert "PROTOTYPE-SECRET" in serialized_trace
    assert SENTINEL_COMMAND in serialized_trace
    trace_request = json.loads(trace.request_json or "{}")
    trace_response = json.loads(trace.response_json or "{}")
    assert trace_request["prompt"] == task.prompt
    assert trace_response["result"] == SENTINEL_PAYLOAD
    assert any(SENTINEL_COMMAND in item["content"] for item in trace_response["logs"])

    status_event = [event for event in bus.events if event.get("type") == "task_status"][-1]
    serialized_status = json.dumps(status_event, ensure_ascii=False)
    assert "PROTOTYPE-SECRET" in serialized_status
    assert status_event["task_id"] == task.id
    assert status_event["execution_process_id"] == task.last_execution_process_id

    audit_rows: list[dict[str, object]] = []

    class _Sink:
        def record(self, category: str, **kwargs: object) -> None:
            audit_rows.append({"category": category, **kwargs})

    audit_payload = dict(status_event)
    audit_payload.pop("type")
    record_event(
        {"type": "task_status", "payload": audit_payload},
        sink=cast(AuditSink, _Sink()),
    )
    assert "PROTOTYPE-SECRET" in json.dumps(audit_rows, ensure_ascii=False)


@pytest.mark.asyncio
async def test_ui_engineer_runtime_persists_typed_result_in_message_trace_and_status() -> None:
    task = _task(task_kind="generation_page")
    store = _Store(task)
    bus = _EventBus(store)
    runtime = _Runtime(codex_store=store, log_store=store, event_bus=bus)
    entry = _entry(task)
    outcome = json.dumps(
        {
            "contractVersion": 1,
            "kind": "answer",
            "message": "submitted",
        }
    )
    entry.result_text = outcome
    entry.produced_real_turn = True

    await runtime._mark_task_done(task.id, entry)

    assert json.loads(store.task.result or "{}") == json.loads(outcome)
    assert store.messages[-1].content == outcome
    trace_response = json.loads(store.traces[-1].response_json or "{}")
    assert trace_response["result"] == outcome
    status_event = [event for event in bus.events if event.get("type") == "task_status"][-1]
    assert status_event["result"] == outcome


@pytest.mark.asyncio
async def test_ui_engineer_runtime_trace_does_not_truncate_large_content() -> None:
    task = _task(task_kind="generation_page")
    store = _Store(task)
    runtime = _Runtime(codex_store=store, log_store=store, event_bus=_EventBus(store))
    entry = _entry(task)
    large_payload = json.dumps({"content": f"{'x' * 60_000}TRACE-END"})
    entry.result_text = large_payload
    entry.produced_real_turn = True

    await runtime._mark_task_done(task.id, entry)

    trace = store.traces[-1]
    assert trace.is_truncated is False
    assert "TRACE-END" in (trace.response_json or "")
    assert len(trace.response_preview or "") == 4_000


@pytest.mark.asyncio
async def test_non_prototype_runtime_logging_and_trace_content_are_unchanged() -> None:
    task = _task(task_kind="normal")
    store = _Store(task)
    bus = _EventBus(store)
    runtime = _Runtime(codex_store=store, log_store=store, event_bus=bus)
    entry = _entry(task)

    await runtime._append_log(task.session_id, "stdout", SENTINEL_PAYLOAD, task.id)
    entry.result_text = SENTINEL_PAYLOAD
    entry.produced_real_turn = True
    await runtime._mark_task_done(task.id, entry)

    assert store.logs[-1].content == SENTINEL_PAYLOAD
    assert store.task.result == SENTINEL_PAYLOAD
    assert store.messages[-1].content == SENTINEL_PAYLOAD
    trace_response = json.loads(store.traces[-1].response_json or "{}")
    assert trace_response["result"] == SENTINEL_PAYLOAD
    status_event = [event for event in bus.events if event.get("type") == "task_status"][-1]
    assert status_event["result"] == SENTINEL_PAYLOAD


@pytest.mark.asyncio
async def test_unresolved_task_identity_still_persists_complete_runtime_content() -> None:
    task = _task(task_kind="normal")
    store = _Store(task)
    bus = _EventBus(store)
    runtime = _Runtime(codex_store=store, log_store=store, event_bus=bus)

    await runtime._append_log(
        task.session_id,
        "stdout",
        SENTINEL_PAYLOAD,
        "missing-task-id",
    )

    assert len(store.logs) == 1
    assert store.logs[0].content == SENTINEL_PAYLOAD
