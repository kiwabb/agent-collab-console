"""Asyncio-event registry so the Conductor tool loop can await task completion.

WorkflowScheduler.on_task_completed calls .signal() when a registered task
finishes.  The Conductor's dispatch_subagent tool calls .wait_for() which
blocks until that signal arrives.
"""
from __future__ import annotations

import asyncio
from typing import Any


class TaskCompletionRegistry:
    """Process-singleton registry of in-flight conductor-dispatched tasks."""

    _instance: "TaskCompletionRegistry | None" = None

    def __new__(cls) -> "TaskCompletionRegistry":
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._events: dict[str, asyncio.Event] = {}
            obj._results: dict[str, Any] = {}
            cls._instance = obj
        return cls._instance

    @classmethod
    def get(cls) -> "TaskCompletionRegistry":
        return cls()

    def register(self, task_id: str) -> None:
        self._events[task_id] = asyncio.Event()

    def is_registered(self, task_id: str) -> bool:
        return task_id in self._events

    def signal(self, task_id: str, result: Any) -> None:
        self._results[task_id] = result
        ev = self._events.get(task_id)
        if ev is not None:
            ev.set()

    async def wait_for(self, task_id: str, timeout: float = 600.0) -> Any:
        ev = self._events.get(task_id)
        if ev is None:
            raise LookupError(f"Task {task_id} not registered in completion registry")
        try:
            await asyncio.wait_for(asyncio.shield(ev.wait()), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Task {task_id} did not complete within {timeout}s") from exc
        finally:
            self._events.pop(task_id, None)
        return self._results.pop(task_id, None)
