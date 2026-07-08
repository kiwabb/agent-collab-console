"""Process-local registry enforcing one live Conductor session per issue.

A "session" is the running `run_issue_conductor_loop` asyncio task for an
issue. Routing every start path (auto-start, restart, reset, recovery
relaunch) through `try_start` makes "one issue = one session" an enforced
invariant and gives the recovery watchdog a reliable liveness signal so it
never relaunches a conductor that is still running in this process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field  # noqa: F401
from datetime import datetime


@dataclass
class ConductorSessionHandle:
    issue_id: str
    task: asyncio.Task[object]
    started_at: datetime
    conductor_task_id: str | None = None


class ConductorSessionRegistry:
    """Singleton mapping issue_id -> the live conductor-loop asyncio task."""

    _instance: "ConductorSessionRegistry | None" = None  # noqa: UP037

    def __init__(self) -> None:
        self._sessions: dict[str, ConductorSessionHandle] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> "ConductorSessionRegistry":  # noqa: UP037
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def try_start(
        self,
        issue_id: str,
        coro_factory: Callable[[], Coroutine[object, object, object]],
        *,
        name: str | None = None,
    ) -> ConductorSessionHandle | None:
        """Start a session for `issue_id` unless one is already live.

        Returns the new handle, or None if a live session already exists
        (idempotent skip). The caller may attach further done-callbacks to
        the returned handle's `task`.
        """
        async with self._lock:
            existing = self._sessions.get(issue_id)
            if existing is not None and not existing.task.done():
                return None
            task: asyncio.Task[object] = asyncio.create_task(
                coro_factory(),
                name=name or f"conductor-{issue_id[:8]}",
            )
            handle = ConductorSessionHandle(issue_id=issue_id, task=task, started_at=datetime.now())
            self._sessions[issue_id] = handle

            def cleanup_done_task(_done_task: asyncio.Future[object]) -> None:
                self._on_done(issue_id, task)

            task.add_done_callback(cleanup_done_task)
            return handle

    def _on_done(self, issue_id: str, task: asyncio.Task[object]) -> None:
        # Deregister only if the finished task is still the registered one;
        # a fast restart may have already replaced it.
        handle = self._sessions.get(issue_id)
        if handle is not None and handle.task is task:
            self._sessions.pop(issue_id, None)

    async def bind_conductor_task(self, issue_id: str, conductor_task_id: str) -> None:
        """Record the conductor_task id once the loop has created it."""
        async with self._lock:
            handle = self._sessions.get(issue_id)
            if handle is not None:
                handle.conductor_task_id = conductor_task_id

    def get(self, issue_id: str) -> ConductorSessionHandle | None:
        return self._sessions.get(issue_id)

    def is_alive(self, issue_id: str) -> bool:
        handle = self._sessions.get(issue_id)
        return handle is not None and not handle.task.done()

    def is_conductor_task_alive(self, issue_id: str, conductor_task_id: str) -> bool:
        """True only if this exact conductor_task row is the live session."""
        handle = self._sessions.get(issue_id)
        return (
            handle is not None
            and not handle.task.done()
            and handle.conductor_task_id == conductor_task_id
        )

    def list_all(self) -> list[ConductorSessionHandle]:
        return list(self._sessions.values())

    async def stop(self, issue_id: str) -> bool:
        """Cancel and deregister the session for `issue_id`."""
        async with self._lock:
            handle = self._sessions.get(issue_id)
            if handle is None:
                return False
            if not handle.task.done():
                handle.task.cancel()
            self._sessions.pop(issue_id, None)
            return True
