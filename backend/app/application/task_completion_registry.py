"""Asyncio-event registry so the Conductor tool loop can await task completion.

WorkflowScheduler.on_task_completed calls .signal() when a registered task
finishes.  The Conductor's dispatch_subagent tool calls .wait_for() which
blocks until that signal arrives.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable


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
        ev = self._events.get(task_id)
        if ev is None:
            # No waiter: the dispatch already timed out (and popped its event) or
            # was never registered. Storing the result here would orphan it in
            # `_results` forever, since nothing will ever pop it. Drop it instead.
            return
        self._results[task_id] = result
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

    async def wait_for_active(
        self,
        task_id: str,
        *,
        idle_timeout: float,
        hard_timeout: float,
        activity_age: Callable[[str], float | None] | None = None,
        poll: float = 15.0,
    ) -> Any:
        """Wait for completion without abandoning a task that is still working.

        A flat timeout wrongly gives up on a legitimately slow subagent (e.g. a
        thorough QA pass) that is still streaming output — the dispatch then
        redispatches a duplicate and discards the original's work. Instead, keep
        waiting as long as the task shows recent activity, and only time out on:
          - genuine stall: no activity for `idle_timeout` seconds, or
          - `hard_timeout`: absolute safety ceiling regardless of activity.

        `activity_age(task_id)` returns seconds since the task last emitted
        output, or None when unknown (then only `hard_timeout` applies).
        """
        ev = self._events.get(task_id)
        if ev is None:
            raise LookupError(f"Task {task_id} not registered in completion registry")
        start = time.monotonic()
        try:
            while True:
                try:
                    await asyncio.wait_for(asyncio.shield(ev.wait()), timeout=poll)
                    break
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - start
                    if elapsed >= hard_timeout:
                        raise TimeoutError(
                            f"Task {task_id} did not complete within hard limit {hard_timeout:.0f}s"
                        )
                    if activity_age is not None:
                        age = activity_age(task_id)
                        if age is not None and age >= idle_timeout:
                            raise TimeoutError(
                                f"Task {task_id} idle for {age:.0f}s (limit {idle_timeout:.0f}s)"
                            )
        finally:
            self._events.pop(task_id, None)
        return self._results.pop(task_id, None)
