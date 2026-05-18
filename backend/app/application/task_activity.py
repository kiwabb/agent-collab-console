"""Shared in-memory task-activity tracker used by the stall watchdog.

The runtime touches `last_activity[task_id]` on every LLM stream token; the
watchdog reads it (alongside `task.status` from the store) to decide whether
a task has gone silent past the stall threshold. Both writers and the
watchdog are single-loop asyncio code, so a plain dict is sufficient.
"""
from __future__ import annotations

from datetime import datetime
from typing import Final

# task_id -> datetime of last observed LLM/runtime activity
last_activity: Final[dict[str, datetime]] = {}

# task_id -> datetime when the watchdog last nudged this task (cooldown gate)
last_nudged: Final[dict[str, datetime]] = {}


def touch(task_id: str | None) -> None:
    if not task_id:
        return
    last_activity[task_id] = datetime.now()


def clear(task_id: str | None) -> None:
    if not task_id:
        return
    last_activity.pop(task_id, None)
    last_nudged.pop(task_id, None)


def mark_nudged(task_id: str) -> None:
    last_nudged[task_id] = datetime.now()
