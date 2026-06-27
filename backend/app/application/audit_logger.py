from __future__ import annotations

"""Unified audit-trail writer (PR1).

Single write entry-point for the `audit_log` table. Every choke point — LLM
call/return, tool use/result, QA command exec, git command, CLI spawn, generic
EventBus event, agent finalize — funnels through `audit_logger.record(...)`.
Centralizing the write here is deliberate: the PRD calls for one writer so the
six instrumentation points (added in PR2) can never drift into double-writes or
inconsistent schemas.

Design (mirrors `event_bus.EventBus._db_worker`):
- A background asyncio task drains an `asyncio.Queue`; `record(...)` is
  fire-and-forget enqueue so hot paths never block on the DB.
- best-effort: a write failure is logged at WARNING level and swallowed — it is
  never propagated to the caller (audit logging must not break the thing it is
  auditing).
- Large payloads are truncated with the same 8000-char + `__truncated__`
  strategy used by `conductor_main_loop._prepare_payload` (copied here so this
  module has no dependency on the conductor loop).

PR1 scope: this module + the `audit_log` table are wired up and unit-tested, but
NO choke point calls it yet. Instrumentation is PR2.
"""
import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
from datetime import datetime  # noqa: E402
from typing import Any  # noqa: E402
from uuid import uuid4  # noqa: E402

# Category constants (string enum — no DB-level constraint, matches the PRD).
CATEGORY_LLM_CALL = "llm_call"
CATEGORY_LLM_RETURN = "llm_return"
CATEGORY_TOOL_USE = "tool_use"
CATEGORY_TOOL_RESULT = "tool_result"
CATEGORY_COMMAND_EXEC = "command_exec"
CATEGORY_GIT_COMMAND = "git_command"
CATEGORY_CLI_SPAWN = "cli_spawn"
CATEGORY_EVENT = "event"
CATEGORY_AGENT_FINALIZE = "agent_finalize"

AUDIT_CATEGORIES = frozenset(
    {
        CATEGORY_LLM_CALL,
        CATEGORY_LLM_RETURN,
        CATEGORY_TOOL_USE,
        CATEGORY_TOOL_RESULT,
        CATEGORY_COMMAND_EXEC,
        CATEGORY_GIT_COMMAND,
        CATEGORY_CLI_SPAWN,
        CATEGORY_EVENT,
        CATEGORY_AGENT_FINALIZE,
    }
)

# Payload truncation budget. Same 8000-char ceiling + `__truncated__` marker
# strategy as conductor_main_loop._prepare_payload (intentionally duplicated to
# keep this module dependency-free).
_PAYLOAD_LIMIT = 8000

# Bounded-queue backpressure (PR2). PR2 wires the high-frequency
# `event_bus.append` and `git_service._run` choke points into the audit trail,
# so an unbounded queue could grow without limit if the DB drain falls behind
# (e.g. a slow disk during a burst of fan-out events) and eventually OOM the
# process. Audit logging is best-effort, so a bounded queue with a DROP policy
# is the correct trade: losing a few audit rows under extreme load is strictly
# better than crashing the thing we are auditing.
#
# Drop policy: DROP-NEWEST. When the queue is full we discard the incoming
# entry rather than evicting the oldest queued one. Rationale: the queue drains
# strictly in arrival order, so the already-queued (older) rows are closer to
# being persisted; dropping them to make room for a newer row would waste the
# work of having queued them and bias the trail toward the tail of a burst.
# Dropping the newest keeps the contiguous already-accepted prefix intact and is
# O(1) (no peek/evict). Dropped entries are counted and a throttled WARNING is
# emitted so the loss is observable rather than silent.
_DEFAULT_MAX_QUEUE = int(os.getenv("AUDIT_LOG_MAX_QUEUE", "10000"))
# Emit a dropped-count WARNING at most once per this many drops (avoids a log
# storm when the queue is saturated for a sustained period).
_DROP_WARN_EVERY = 500


def _serialize_payload(payload: Any | None) -> str:
    """JSON-serialize a payload, truncating when it exceeds the budget.

    Mirrors `conductor_main_loop._prepare_payload`: if the serialized form is
    over the limit, replace it with a `{__truncated__, preview, original_length}`
    envelope instead of storing the full blob.
    """
    if payload is None:
        return "{}"
    try:
        raw = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = json.dumps({"repr": repr(payload)}, ensure_ascii=False, default=str)
    if len(raw) <= _PAYLOAD_LIMIT:
        return raw
    truncated = {
        "__truncated__": True,
        "preview": raw[: max(0, _PAYLOAD_LIMIT - 64)],
        "original_length": len(raw),
    }
    return json.dumps(truncated, ensure_ascii=False, default=str)


class AuditLogger:
    """Async, non-blocking, best-effort writer for the `audit_log` table.

    Lifecycle mirrors EventBus: `set_store(...)` + `set_loop(...)` (order
    independent) spin up the background drain task once both are present.
    `record(...)` enqueues fire-and-forget. `shutdown()` stops the worker.
    """

    def __init__(self, max_queue: int | None = None) -> None:
        self._store = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Bounded queue: full -> drop-newest (see module docstring). maxsize<=0
        # would mean unbounded; clamp to at least 1 so the bound is always real.
        size = _DEFAULT_MAX_QUEUE if max_queue is None else max_queue
        self._max_queue = max(1, int(size))
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._worker_task: asyncio.Task | None = None
        self._lock = threading.Lock()
        # Backpressure observability: total dropped since process start.
        self._dropped = 0

    # --- lifecycle -----------------------------------------------------------

    def set_store(self, store) -> None:
        self._store = store
        self._maybe_start_worker()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._maybe_start_worker()

    def _maybe_start_worker(self) -> None:
        with self._lock:
            if self._worker_task is not None:
                return
            if self._store is None or self._loop is None:
                return
            self._worker_task = self._loop.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            entry = await self._queue.get()
            try:
                if entry is None:  # shutdown sentinel
                    break
                if self._store is not None:
                    await self._store.save_audit_log(entry)
            except Exception as exc:  # noqa: BLE001, RUF100
                print(f"[AuditLogger] write error: {exc}", file=sys.stderr)
            finally:
                self._queue.task_done()

    async def shutdown(self) -> None:
        if self._worker_task is None:
            return
        await self._queue.put(None)
        try:  # noqa: SIM105
            await self._worker_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001, RUF100
            pass
        self._worker_task = None

    # --- write API -----------------------------------------------------------

    def _build_entry(
        self,
        category: str,
        *,
        actor: str | None,
        issue_id: str | None,
        task_id: str | None,
        conductor_task_id: str | None,
        execution_process_id: str | None,
        correlation_id: str | None,
        status: str | None,
        duration_ms: int | None,
        payload: Any | None,
        error: str | None,
    ):
        from app.domain.models import AuditLog

        return AuditLog(
            id=f"audit-{uuid4().hex}",
            category=category,
            created_at=datetime.now(),
            actor=actor,
            issue_id=issue_id,
            task_id=task_id,
            conductor_task_id=conductor_task_id,
            execution_process_id=execution_process_id,
            correlation_id=correlation_id,
            status=status,
            duration_ms=duration_ms,
            payload_json=_serialize_payload(payload),
            error=error,
        )

    def _note_drop(self) -> None:
        """Account for a dropped entry and emit a throttled WARNING.

        Best-effort and never raises: backpressure accounting must not itself
        become a failure mode on the hot path.
        """
        self._dropped += 1
        if self._dropped == 1 or self._dropped % _DROP_WARN_EVERY == 0:
            print(
                f"[AuditLogger] queue full (maxsize={self._max_queue}); dropped "
                f"{self._dropped} audit entries (drop-newest, best-effort)",
                file=sys.stderr,
            )

    def _put_or_drop(self, entry) -> None:
        """put_nowait, counting a drop instead of raising when the queue is full."""
        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            self._note_drop()

    def _enqueue(self, entry) -> None:
        """Thread-safe enqueue that always wakes the worker's `queue.get()`.

        `asyncio.Queue` is NOT thread-safe: calling `put_nowait` from a thread
        other than the worker's loop thread enqueues the item but does NOT wake
        the `await queue.get()` waiter, so the row can stall indefinitely until
        some unrelated same-loop activity happens to drain it. PR2 wires sync
        choke points (`git_service._run`, `event_bus.append`, CLI spawn) that may
        run off the loop thread, so we hop onto the loop via
        `call_soon_threadsafe` whenever a loop is set. With no loop yet
        (buffering before startup), a plain `put_nowait` is correct because there
        is no waiter to wake — the worker drains the backlog on first `get()`.

        The queue is bounded (drop-newest): when it is full, `put_nowait` raises
        `QueueFull` which `_put_or_drop` swallows + counts. On the off-loop path
        the `QueueFull` would otherwise surface inside the loop callback (where
        nobody catches it), so we route that path through `_put_or_drop` too.
        """
        loop = self._loop
        if loop is None:
            # No worker loop yet: buffer directly. There is no waiter to wake, so
            # a plain put is correct; the worker drains the backlog on its first
            # get() once started. Still bounded -> drop-newest if it fills.
            self._put_or_drop(entry)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            # Already on the worker's loop thread: enqueue synchronously so
            # callers that immediately await `drain()`/`join()` observe the put
            # (call_soon_threadsafe would defer it past join() and race).
            self._put_or_drop(entry)
        else:
            # Off the loop thread (sync choke point on another thread): hop onto
            # the loop so the worker's `queue.get()` waiter is actually woken.
            # _put_or_drop runs inside the callback so a QueueFull is counted,
            # not raised into the loop's exception handler.
            loop.call_soon_threadsafe(self._put_or_drop, entry)

    def record(
        self,
        category: str,
        *,
        actor: str | None = None,
        issue_id: str | None = None,
        task_id: str | None = None,
        conductor_task_id: str | None = None,
        execution_process_id: str | None = None,
        correlation_id: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
        payload: Any | None = None,
        error: str | None = None,
    ) -> None:
        """Enqueue an audit row, fire-and-forget. Never raises.

        Safe to call from sync or async contexts and from any thread: it only
        enqueues (thread-safely hopping onto the worker's loop when one is set).
        If the worker is not running yet (store/loop not wired), the entry
        buffers in the queue and drains once the worker starts.
        """
        try:
            entry = self._build_entry(
                category,
                actor=actor,
                issue_id=issue_id,
                task_id=task_id,
                conductor_task_id=conductor_task_id,
                execution_process_id=execution_process_id,
                correlation_id=correlation_id,
                status=status,
                duration_ms=duration_ms,
                payload=payload,
                error=error,
            )
            self._enqueue(entry)
        except Exception as exc:  # noqa: BLE001, RUF100
            print(f"[AuditLogger] enqueue error: {exc}", file=sys.stderr)

    @property
    def dropped(self) -> int:
        """Total audit entries dropped due to a full queue since process start."""
        return self._dropped

    async def drain(self) -> None:
        """Block until the queue is empty. Test/shutdown helper only."""
        await self._queue.join()


# Global singleton (mirrors event_bus.event_bus).
audit_logger = AuditLogger()
