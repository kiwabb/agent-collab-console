"""Asyncio-event registry so the Conductor tool loop can await task completion.

WorkflowScheduler.on_task_completed calls .signal() when a registered task
finishes.  The Conductor's dispatch_subagent tool calls .wait_for() which
blocks until that signal arrives.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable  # noqa: UP035


class TaskCompletionRegistry:
    """Process-singleton registry of in-flight conductor-dispatched tasks."""

    _instance: "TaskCompletionRegistry | None" = None  # noqa: UP037

    # Defensive buffer of results that arrived BEFORE their task was registered.
    # Bounded + time-pruned so a truly-never-registered task can't leak forever
    # (see _prune_pending / _PENDING_TTL_S / _PENDING_MAX).
    _PENDING_TTL_S: float = 1800.0
    _PENDING_MAX: int = 256

    def __new__(cls) -> "TaskCompletionRegistry":  # noqa: UP037
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._events: dict[str, asyncio.Event] = {}
            obj._results: dict[str, Any] = {}
            obj._aliases: dict[str, str] = {}
            # task_id -> (result, monotonic_ts) for signal-before-register.
            obj._pending: dict[str, tuple[Any, float]] = {}
            cls._instance = obj
        return cls._instance

    @classmethod
    def get(cls) -> "TaskCompletionRegistry":  # noqa: UP037
        return cls()

    def register(self, task_id: str) -> None:
        # Idempotent: never clobber an existing event (which may already be set
        # by an early signal). Re-registering the same task_id is a no-op.
        ev = self._events.get(task_id)
        if ev is None:
            ev = asyncio.Event()
            self._events[task_id] = ev
        # Drain a result that arrived before this register (signal-before-register
        # race). Surface it immediately so the waiter doesn't block.
        pending = self._pending.pop(task_id, None)
        if pending is not None:
            self._results[task_id] = pending[0]
            ev.set()

    def is_registered(self, task_id: str) -> bool:
        return task_id in self._events or self._aliases.get(task_id) in self._events

    def transfer(self, from_task_id: str, to_task_id: str) -> bool:
        """Route future completion signals for ``to_task_id`` to ``from_task_id``.

        Auto-retry creates a fresh task while the Conductor is already awaiting
        the original task id. This alias preserves the original waiter while
        allowing the retry's terminal event to unblock it.
        """
        if from_task_id not in self._events:
            return False
        self._aliases[to_task_id] = from_task_id
        return True

    def _prune_pending(self) -> None:
        """Evict stale/excess buffered results so truly-never-registered tasks
        cannot grow `_pending` without bound."""
        if not self._pending:
            return
        now = time.monotonic()
        stale = [tid for tid, (_, ts) in self._pending.items() if now - ts >= self._PENDING_TTL_S]
        for tid in stale:
            self._pending.pop(tid, None)
        if len(self._pending) > self._PENDING_MAX:
            # Drop oldest first until under the cap.
            ordered = sorted(self._pending.items(), key=lambda kv: kv[1][1])
            for tid, _ in ordered[: len(self._pending) - self._PENDING_MAX]:
                self._pending.pop(tid, None)

    def signal(self, task_id: str, result: Any) -> None:
        target_task_id = self._aliases.get(task_id, task_id)
        ev = self._events.get(target_task_id)
        if ev is None:
            # Signal-before-register: the task runner finished (e.g. instant
            # executor_failed_to_start fail-fast) before the dispatcher called
            # register(). Buffer the result so register()/wait_for_active() can
            # pick it up instead of dropping it and stalling the dispatch until
            # hard_timeout. Bounded + TTL-pruned so a task that is NEVER
            # registered can't orphan the buffer forever.
            self._pending[target_task_id] = (result, time.monotonic())
            self._prune_pending()
            return
        self._results[target_task_id] = result
        ev.set()

    async def wait_for(self, task_id: str, timeout: float = 600.0) -> Any:
        ev = self._events.get(task_id)
        if ev is None:
            # If a result was buffered before registration, surface it now.
            pending = self._pending.pop(task_id, None)
            if pending is not None:
                return pending[0]
            raise LookupError(f"Task {task_id} not registered in completion registry")
        try:
            await asyncio.wait_for(asyncio.shield(ev.wait()), timeout=timeout)
        except asyncio.TimeoutError as exc:  # noqa: UP041
            raise TimeoutError(f"Task {task_id} did not complete within {timeout}s") from exc
        finally:
            self._events.pop(task_id, None)
            self._aliases = {
                alias: target for alias, target in self._aliases.items() if target != task_id
            }
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
            # If a result was buffered before registration, surface it now.
            pending = self._pending.pop(task_id, None)
            if pending is not None:
                return pending[0]
            raise LookupError(f"Task {task_id} not registered in completion registry")
        start = time.monotonic()
        try:
            while True:
                try:
                    await asyncio.wait_for(asyncio.shield(ev.wait()), timeout=poll)
                    break
                except asyncio.TimeoutError:  # noqa: UP041
                    elapsed = time.monotonic() - start
                    if elapsed >= hard_timeout:
                        raise TimeoutError(  # noqa: B904
                            f"Task {task_id} did not complete within hard limit {hard_timeout:.0f}s"
                        )
                    if activity_age is not None:
                        age = activity_age(task_id)
                        alias_ages = [
                            activity_age(alias)
                            for alias, target in self._aliases.items()
                            if target == task_id
                        ]
                        known_ages = [value for value in [age, *alias_ages] if value is not None]
                        age = min(known_ages) if known_ages else None
                        if age is not None and age >= idle_timeout:
                            raise TimeoutError(  # noqa: B904
                                f"Task {task_id} idle for {age:.0f}s (limit {idle_timeout:.0f}s)"
                            )
        finally:
            self._events.pop(task_id, None)
            self._aliases = {
                alias: target for alias, target in self._aliases.items() if target != task_id
            }
        return self._results.pop(task_id, None)
