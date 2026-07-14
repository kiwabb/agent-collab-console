from __future__ import annotations

import asyncio
from datetime import datetime
from typing import cast

import pytest

from app.application.claude_process_runtime import ClaudeProcessRuntime
from app.application.process_runtime_common import AsyncProcessEntry, RuntimeCodexStore
from app.domain.models import CodexTask


class _Process:
    returncode: int | None = None


class _Store:
    def __init__(self, task: CodexTask) -> None:
        self.task = task

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        return self.task if task_id == self.task.id else None


@pytest.mark.asyncio
async def test_claude_wait_timeout_terminates_before_returning(monkeypatch) -> None:
    task = CodexTask(
        id="task-timeout",
        session_id="workspace-1",
        title="Prototype UI",
        prompt="Generate",
        role="prototype_ui_engineer",
        status="running",
        last_execution_process_id="process-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    store = _Store(task)
    process = _Process()
    entry = AsyncProcessEntry(
        proc=cast(asyncio.subprocess.Process, process),
        output_task=None,
        alive=True,
        session_id=task.session_id,
        executor="claude",
        cwd="/tmp/worktree",
        resume_session_id=None,
        task_id=task.id,
    )
    runtime = ClaudeProcessRuntime.__new__(ClaudeProcessRuntime)
    runtime.codex_store = cast(RuntimeCodexStore, store)
    runtime._processes = {task.id: entry}
    calls: list[str] = []

    async def cleanup(process_key: str, timed_out_entry: AsyncProcessEntry) -> None:
        assert process_key == task.id
        timed_out_entry.alive = False
        process.returncode = -15
        calls.append("cleanup")

    async def mark_failed(task_id: str, timed_out_entry: AsyncProcessEntry) -> None:
        assert calls == ["cleanup"]
        assert task_id == task.id
        task.status = "failed"
        task.result = timed_out_entry.result_text
        calls.append("failed")

    monkeypatch.setattr(runtime, "_cleanup_entry", cleanup)
    monkeypatch.setattr(runtime, "_mark_task_failed", mark_failed)

    await runtime._abort_wait_timeout(
        task.id,
        entry,
        task_id=task.id,
        timeout_s=600,
    )

    assert calls == ["cleanup", "failed"]
    assert task.id not in runtime._processes
    assert entry.alive is False
    assert process.returncode == -15
    assert task.status == "failed"
    assert task.result == "Claude runtime exceeded maximum wait of 600 seconds"
