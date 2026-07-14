"""Reader-loop hardening tests (process_runtime_common._reader_loop).

The reader loop must ALWAYS reap its subprocess and finalize the task when it
exits — for any reason (EOF, idle timeout, readline exception) — and must never
deadlock on the finally-block stderr drain.
"""

from __future__ import annotations

import asyncio
import time
from asyncio.subprocess import Process
from datetime import datetime
from typing import cast

import pytest

from app.application.process_runtime_common import AsyncProcessEntry, BaseProcessRuntime
from app.domain.models import CodexSession, CodexTask, ExecutionProcess, HelpRequest, LogEvent


class StoreStub:
    def __init__(self, task: CodexTask, workspace: CodexSession, process: ExecutionProcess):
        self.task = task
        self.workspace = workspace
        self.processes = {process.id: process}

    async def load_codex_task(self, task_id):
        return self.task if task_id == self.task.id else None

    async def save_codex_task(self, task):
        self.task = task

    async def load_codex_workspace(self, workspace_id):
        return self.workspace if workspace_id == self.workspace.id else None

    async def save_codex_workspace(self, workspace):
        self.workspace = workspace

    async def update_execution_process_status(
        self, process_id, status, exit_code=None, completed_at=None
    ):
        p = self.processes.get(process_id)
        if p:
            p.status = status
            p.exit_code = exit_code

    async def load_execution_process(self, process_id):
        return self.processes.get(process_id)

    async def save_codex_task_message(self, message):
        return None

    async def list_codex_task_messages(self, task_id, execution_process_id=None):
        return []

    async def update_execution_process_usage(
        self,
        process_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        total_cost_usd: float | None = None,
    ) -> None:
        return None

    async def load_help_request(self, help_request_id: str) -> HelpRequest | None:
        return None


class TerminalSaveGateStore(StoreStub):
    """Keep loaded task objects detached so the test observes real saves."""

    def __init__(self, task: CodexTask, workspace: CodexSession, process: ExecutionProcess):
        super().__init__(task.model_copy(deep=True), workspace, process)
        self.terminal_save_started = asyncio.Event()
        self.allow_terminal_save = asyncio.Event()
        self._blocked_terminal_save = False

    async def load_codex_task(self, task_id):
        if task_id != self.task.id:
            return None
        return self.task.model_copy(deep=True)

    async def save_codex_task(self, task):
        if (
            task.status == "done"
            and task.result == '{"submission":"accepted"}'
            and not self._blocked_terminal_save
        ):
            self._blocked_terminal_save = True
            self.terminal_save_started.set()
            await self.allow_terminal_save.wait()
        self.task = task.model_copy(deep=True)


class LogStoreStub:
    async def append_log_event(self, event: LogEvent) -> None:
        return None


class EventBusStub:
    def __init__(self):
        self.events = []

    async def queue_log_event(self, event):
        return None

    async def append(self, event):
        self.events.append(event)


class _Runtime(BaseProcessRuntime):
    def _owns_entry(self, entry):
        return True


class FakeStdout:
    def __init__(self, behavior):
        self._behavior = behavior

    async def readline(self):
        return await self._behavior()


class FakeStderr:
    def __init__(self, data=b"", hang=False):
        self._data = data
        self._hang = hang

    async def read(self, n=-1):
        if self._hang:
            await asyncio.sleep(3600)  # would deadlock if not bounded
        return self._data


class FakeProc:
    def __init__(self, stdout, stderr, returncode=None):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True
        if self.returncode is None:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


def _fixture(returncode=None, stdout=None, stderr=None):
    now = datetime.now()
    process = ExecutionProcess(
        id="ep-1",
        task_id="task-1",
        session_id="workspace-1",
        status="Running",
        created_at=now,
        updated_at=now,
    )
    task = CodexTask(
        id="task-1",
        session_id="workspace-1",
        title="t",
        prompt="p",
        status="responding",
        executor="claude",
        last_execution_process_id="ep-1",
        created_at=now,
        updated_at=now,
    )
    workspace = CodexSession(
        id="workspace-1",
        title="W",
        cwd="/tmp",
        created_at=now,
        last_active_at=now,
    )
    store = StoreStub(task, workspace, process)
    bus = EventBusStub()
    runtime = _Runtime(
        codex_store=store,
        log_store=LogStoreStub(),
        event_bus=bus,
        refresh_task_result=None,
    )
    proc = FakeProc(stdout, stderr, returncode=returncode)
    entry = AsyncProcessEntry(
        proc=cast(Process, proc),
        output_task=None,
        alive=True,
        session_id="workspace-1",
        executor="claude",
        cwd="/tmp",
        resume_session_id=None,
        task_id="task-1",
    )
    return runtime, store, entry, proc


@pytest.mark.asyncio
async def test_reader_waiter_releases_only_after_terminal_result_is_persisted():
    result = '{"submission":"accepted"}'
    frames = [
        b'{"type":"result","is_error":false,"result":'
        b'"{\\"submission\\":\\"accepted\\"}"}\n',
        b"",
    ]

    async def terminal_then_eof():
        return frames.pop(0)

    runtime, original_store, entry, _ = _fixture(
        returncode=0,
        stdout=FakeStdout(terminal_then_eof),
        stderr=FakeStderr(data=b""),
    )
    process = original_store.processes["ep-1"]
    store = TerminalSaveGateStore(original_store.task, original_store.workspace, process)
    runtime.codex_store = store
    waiter = asyncio.Event()
    entry.pending_waiters.append(waiter)

    reader = asyncio.create_task(runtime._reader_loop("workspace-1", entry, "task-1"))
    await asyncio.wait_for(store.terminal_save_started.wait(), timeout=1)

    assert waiter.is_set() is False
    assert store.task.status == "responding"
    assert store.task.result is None

    store.allow_terminal_save.set()
    await asyncio.wait_for(waiter.wait(), timeout=1)

    assert store.task.status == "done"
    assert store.task.result == result
    await asyncio.wait_for(reader, timeout=1)


@pytest.mark.asyncio
async def test_reader_loop_reaps_process_on_readline_exception(monkeypatch):
    """A >64KB line (LimitOverrunError) must NOT orphan the process: the loop
    reaps it and finalizes the task as failed."""

    async def raise_overrun():
        raise asyncio.LimitOverrunError("line too long", 100)

    runtime, store, entry, proc = _fixture(
        returncode=None,
        stdout=FakeStdout(raise_overrun),
        stderr=FakeStderr(data=b""),
    )

    await asyncio.wait_for(runtime._reader_loop("workspace-1", entry, "task-1"), timeout=5)

    assert proc.terminated is True  # 5a: process reaped
    assert entry.had_error is True  # 5c: overrun recorded as error
    assert store.task.status == "failed"  # task finalized, not left "responding"


@pytest.mark.asyncio
async def test_reader_loop_stderr_drain_is_bounded(monkeypatch):
    """A hanging stderr.read must not deadlock the finally — it is bounded by
    a wait_for, so the reader loop returns promptly."""

    async def eof():
        return b""  # immediate EOF → loop breaks normally

    runtime, store, entry, proc = _fixture(  # noqa: RUF059
        returncode=0,  # already exited → finally skips terminate
        stdout=FakeStdout(eof),
        stderr=FakeStderr(hang=True),  # read() would hang forever
    )

    start = time.monotonic()
    await asyncio.wait_for(runtime._reader_loop("workspace-1", entry, "task-1"), timeout=5)
    elapsed = time.monotonic() - start
    assert elapsed < 4  # bounded by the 2s stderr wait_for, not the 3600s hang


@pytest.mark.asyncio
async def test_reader_loop_terminates_process_even_when_not_idle(monkeypatch):
    """5a regression: a normal EOF exit with a still-live process (returncode
    None) must still reap the subprocess."""

    async def eof():
        return b""

    runtime, store, entry, proc = _fixture(  # noqa: RUF059
        returncode=None,  # still "alive" at loop exit
        stdout=FakeStdout(eof),
        stderr=FakeStderr(data=b""),
    )

    await asyncio.wait_for(runtime._reader_loop("workspace-1", entry, "task-1"), timeout=5)
    assert proc.terminated is True  # reaped despite not being idle-timed-out
