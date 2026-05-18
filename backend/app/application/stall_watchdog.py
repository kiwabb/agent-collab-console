"""Stall watchdog — nudges agents that have been silent past the threshold.

How it works:
- `task_activity.touch(task_id)` is called from the runtime on every LLM
  stream event; the watchdog reads that timestamp.
- Every WATCHDOG_INTERVAL_S seconds the watchdog scans all in-flight tasks
  (status in {running, responding}). If a task has been silent for more
  than STALL_THRESHOLD_S, the watchdog:
    1. terminate_task(task_id)   → kills the hung HTTP/process call;
                                    runtime marks task.status = "failed".
    2. Sends a chat message to the same task   → start_task_run creates a
                                                  new EP with kind="chat",
                                                  the agent gets the nudge
                                                  text as its next turn.
- Per-task cooldown (NUDGE_COOLDOWN_S) prevents repeated nudging.

Environment knobs (all optional):
    CODEX_STALL_WATCHDOG=true|false      (default: true)
    CODEX_STALL_THRESHOLD_S=180          (default: 180s == 3min)
    CODEX_STALL_INTERVAL_S=30            (default: 30s scan cadence)
    CODEX_STALL_COOLDOWN_S=300           (default: 300s between nudges per task)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from app.application import task_activity

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 30
DEFAULT_THRESHOLD = 180
DEFAULT_COOLDOWN = 300

NUDGE_PROMPT = (
    "[WATCHDOG] 你刚才超过 {silence_s:.0f} 秒没有输出任何内容。请总结一下当前正在做的事情，"
    "然后**直接给出最终结果**（按照原本的产物 schema），不要再做更多调研——你已经收集到的信息足够了。"
    "如果某些细节不确定，按合理默认值填，并在 risks 字段简短说明。"
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


async def _scan_once(store, process_manager, run_task_with_user_content) -> None:
    threshold = _env_int("CODEX_STALL_THRESHOLD_S", DEFAULT_THRESHOLD)
    cooldown = _env_int("CODEX_STALL_COOLDOWN_S", DEFAULT_COOLDOWN)
    now = datetime.now()
    try:
        tasks = await store.list_codex_tasks()
    except Exception as exc:
        logger.warning("watchdog: failed to list tasks: %s", exc)
        return

    def _field(t, name, default=None):
        # list_codex_tasks returns dicts; load_codex_task returns CodexTask.
        # Support both transparently so the watchdog works regardless.
        if isinstance(t, dict):
            return t.get(name, default)
        return getattr(t, name, default)

    for task in tasks:
        task_id = _field(task, "id")
        if not task_id:
            continue
        status = (_field(task, "status") or "").lower()
        if status not in {"running", "responding"}:
            # Not in flight — clean trackers so a future re-run starts fresh.
            task_activity.clear(task_id)
            continue
        # Skip help-blocked tasks; silence is expected while waiting on a child.
        if _field(task, "blocked_by_help_id"):
            continue
        last = task_activity.last_activity.get(task_id)
        if last is None:
            # No activity recorded yet — runtime may not have streamed a token
            # since startup. Seed it now and re-evaluate next cycle.
            task_activity.touch(task_id)
            continue
        silence_s = (now - last).total_seconds()
        if silence_s < threshold:
            continue
        last_nudge = task_activity.last_nudged.get(task_id)
        if last_nudge and (now - last_nudge).total_seconds() < cooldown:
            continue

        logger.warning(
            "watchdog: task %s (%s/%s) silent for %.0fs — terminating + nudging",
            task_id,
            _field(task, "role", "?"),
            _field(task, "executor", "?"),
            silence_s,
        )
        task_activity.mark_nudged(task_id)
        # Shield terminate_task: process_runtime._cleanup_entry only catches
        # Exception, but its `await wait_for(shield(output_task))` re-raises
        # CancelledError when the cancelled SDK task winds down. Without
        # the shield, that CancelledError tears the watchdog down. We need
        # the cancel to stop the agent's run, not us.
        try:
            await asyncio.shield(process_manager.terminate_task(task_id))
        except asyncio.CancelledError:
            # Either an in-band cancel from cleanup_entry (transient and OK
            # to ignore) or a real shutdown signal. If the outer event loop
            # actually wants us gone, the next `await` will re-raise.
            logger.info(
                "watchdog: absorbed CancelledError from terminate_task(%s) — assuming in-band cancel; continuing",
                task_id,
            )
        except Exception as exc:
            logger.warning("watchdog: terminate_task(%s) failed: %s", task_id, exc)
            continue
        # Give the runtime a beat to flush the task_status=failed event so the
        # scheduler doesn't see status=responding when chat re-launches.
        await asyncio.sleep(0.5)
        try:
            await asyncio.shield(
                run_task_with_user_content(
                    task_id,
                    NUDGE_PROMPT.format(silence_s=silence_s),
                    kind="chat",
                )
            )
        except asyncio.CancelledError:
            logger.info(
                "watchdog: absorbed CancelledError from chat nudge for %s; will re-evaluate next cycle",
                task_id,
            )
        except Exception as exc:
            logger.warning(
                "watchdog: chat nudge for task %s failed (%s); leaving it failed for user/scheduler to handle",
                task_id,
                exc,
            )


async def run(store, get_process_manager, run_task_with_user_content) -> None:
    """Long-running watchdog loop. Cancel via task.cancel() on shutdown."""
    if not _env_bool("CODEX_STALL_WATCHDOG", True):
        logger.info("stall watchdog disabled via CODEX_STALL_WATCHDOG=false")
        return
    interval = _env_int("CODEX_STALL_INTERVAL_S", DEFAULT_INTERVAL)
    threshold = _env_int("CODEX_STALL_THRESHOLD_S", DEFAULT_THRESHOLD)
    logger.info(
        "stall watchdog started: scan every %ds, stall threshold %ds",
        interval, threshold,
    )
    try:
        while True:
            try:
                pm = get_process_manager()
                await _scan_once(store, pm, run_task_with_user_content)
            except Exception as exc:
                # Never let a transient bug kill the watchdog.
                logger.exception("watchdog scan crashed: %s", exc)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("stall watchdog stopped")
        raise
