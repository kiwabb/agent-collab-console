from __future__ import annotations

"""Process-wide per-role concurrency limiter for Conductor dispatch.

``MAX_CONCURRENT_INSTANCES_PER_ROLE`` caps how many subagents of the *same*
role may run at once across every issue/conductor in this process. Without it,
the conductor's new same-turn parallel dispatch (and several conductors running
different issues at once) could spawn an unbounded number of e.g. ``engineer``
runs and exhaust executor/API capacity.

The limiter hands out a slot for the *lifetime of a subagent run*:
``dispatch_subagent`` acquires before dispatching and releases when the run
finishes (or times out), so the bound reflects genuinely in-flight work.

Single-loop asyncio: a plain ``asyncio.Semaphore`` per role is sufficient; the
only shared mutation is lazily creating the per-role semaphore, which happens in
a synchronous (no-``await``) section and so is atomic with respect to other
coroutines.
"""
import asyncio  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from app.application import timeouts  # noqa: E402


class RoleConcurrencyLimiter:
    """Process-singleton: one bounded semaphore per role key."""

    _instance: "RoleConcurrencyLimiter | None" = None  # noqa: UP037

    def __new__(cls) -> "RoleConcurrencyLimiter":  # noqa: UP037
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._semaphores = {}
            obj._limit = None
            cls._instance = obj
        return cls._instance

    @classmethod
    def instance(cls) -> "RoleConcurrencyLimiter":  # noqa: UP037
        return cls()

    def _semaphore_for(self, role: str) -> asyncio.Semaphore:
        # Pin the limit on first use so a mid-run env change can't desync the
        # count of an already-created semaphore from a freshly-created one.
        if self._limit is None:
            self._limit = timeouts.max_concurrent_instances_per_role()
        sem = self._semaphores.get(role)
        if sem is None:
            sem = asyncio.Semaphore(self._limit)
            self._semaphores[role] = sem
        return sem

    async def acquire(self, role: str, *, timeout: float) -> bool:
        """Acquire a slot for ``role``; return False if none frees within ``timeout``.

        A non-positive ``timeout`` means "do not wait": acquire only if a slot is
        immediately free.
        """
        sem = self._semaphore_for(role)
        if timeout <= 0:
            # ``Semaphore.acquire()`` only suspends when the count is exhausted
            # (``locked()``). When a slot is free it decrements and returns
            # without ever awaiting, so this is a true non-blocking acquire —
            # and version-independent (no acquire_nowait, no wait_for(…, 0)
            # which would cancel-then-fail even with a slot available).
            if sem.locked():
                return False
            await sem.acquire()
            return True
        try:
            await asyncio.wait_for(sem.acquire(), timeout=timeout)
            return True
        except asyncio.TimeoutError:  # noqa: UP041
            return False

    def release(self, role: str) -> None:
        sem = self._semaphores.get(role)
        if sem is not None:
            sem.release()

    @asynccontextmanager
    async def slot(self, role: str, *, timeout: float):
        """Async context manager that holds a role slot, or yields False on timeout.

        Usage::

            async with limiter.slot(role, timeout=t) as acquired:
                if not acquired:
                    return role_busy_payload
                ...  # run the subagent
        """
        acquired = await self.acquire(role, timeout=timeout)
        try:
            yield acquired
        finally:
            if acquired:
                self.release(role)
