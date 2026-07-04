from __future__ import annotations

"""Stall watchdog — nudges agents that have been silent past the threshold.

How it works:
- `task_activity.touch(task_id)` is called from the runtime on every LLM
  stream event; the watchdog reads that timestamp.
- Every WATCHDOG_INTERVAL_S seconds the watchdog scans all active tasks
  (`task_statuses.is_task_active_status`). If a task has been silent for more
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
import asyncio  # noqa: E402
import logging  # noqa: E402
from datetime import datetime  # noqa: E402

from app.application import task_activity, timeouts  # noqa: E402
from app.application.task_statuses import (  # noqa: E402
    is_task_active_status,
    is_task_failure_status,
)

logger = logging.getLogger(__name__)

NUDGE_PROMPT = (
    "[WATCHDOG] 你刚才超过 {silence_s:.0f} 秒没有输出任何内容。请总结一下当前正在做的事情，"  # noqa: RUF001
    "然后**直接给出最终结果**（按照原本的产物 schema），不要再做更多调研——你已经收集到的信息足够了。"  # noqa: RUF001
    "如果某些细节不确定，按合理默认值填，并在 risks 字段简短说明。"  # noqa: RUF001
)

async def _emit_stall_event(event_type: str, **fields) -> None:
    """GAP I: structured stall lifecycle events on the global bus so stalls are
    countable per role/executor instead of grep-only. Best-effort."""
    try:
        from app.application.event_bus import event_bus

        await event_bus.append({"type": event_type, **fields})
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("stall event %s emit failed: %s", event_type, exc)


async def _scan_once(store, process_manager, run_task_with_user_content) -> None:
    threshold = timeouts.stall_threshold_s()
    cooldown = timeouts.stall_cooldown_s()
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
        status = _field(task, "status")
        if not is_task_active_status(status):
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

        role = _field(task, "role", "?")
        executor = _field(task, "executor", "?")
        logger.warning(
            "watchdog: task %s (%s/%s) silent for %.0fs — terminating + nudging",
            task_id,
            role,
            executor,
            silence_s,
        )
        await _emit_stall_event(
            "stall_detected",
            task_id=task_id,
            issue_id=_field(task, "issue_id"),
            role=role,
            executor=executor,
            silence_s=round(silence_s, 1),
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
            continue
        except Exception as exc:
            logger.warning(
                "watchdog: chat nudge for task %s failed (%s); leaving it failed for user/scheduler to handle",
                task_id,
                exc,
            )
            continue
        # GAP F: the nudge ran as kind="chat", which does NOT persist artifacts
        # or update task.result — so an agent that DID emit its final structured
        # result after the nudge would have it silently dropped. Recover it:
        # promote the task to `done` and run refresh_task_result, which extracts
        # the nudge EP's output from the logs and persists it (and runs GAP E
        # schema validation). If nothing usable was recovered, restore `failed`
        # so the conductor still re-dispatches — worst case identical to before.
        recovered = await _recover_nudge_result(store, process_manager, task_id)
        await _emit_stall_event(
            "stall_recovered" if recovered else "stall_nudge_failed",
            task_id=task_id,
            issue_id=_field(task, "issue_id"),
            role=role,
            executor=executor,
        )


async def _recover_nudge_result(store, process_manager, task_id: str) -> bool:
    """Persist a structured result the agent emitted in response to a nudge.

    Returns True if a usable result was recovered and the task marked done.
    """
    from app.application.process_runtime_common import is_unusable_result_text

    refresh = getattr(process_manager, "refresh_task_result", None)
    if not callable(refresh):
        return False
    try:
        task = await store.load_codex_task(task_id)
        status = getattr(task, "status", None)
        if task is None or (
            not is_task_active_status(status) and not is_task_failure_status(status)
        ):
            return False
        # Promote so refresh_task_result extracts + persists from the nudge EP.
        task.status = "done"
        await refresh(task)
        recovered = bool(task.result) and not is_unusable_result_text(task.result)
        if recovered:
            logger.info("watchdog: recovered nudge result for task %s — marked done", task_id)
            await store.save_codex_task(task)
            return True
        # Nothing usable; keep it failed for the conductor to re-dispatch.
        task.status = "failed"
        await store.save_codex_task(task)
        return False
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.warning("watchdog: nudge result recovery failed for %s: %s", task_id, exc)
        return False


async def run(store, get_process_manager, run_task_with_user_content) -> None:
    """Long-running watchdog loop. Cancel via task.cancel() on shutdown."""
    if not timeouts.stall_watchdog_enabled():
        logger.info("stall watchdog disabled via CODEX_STALL_WATCHDOG=false")
        return
    interval = timeouts.stall_interval_s()
    threshold = timeouts.stall_threshold_s()
    logger.info(
        "stall watchdog started: scan every %ds, stall threshold %ds",
        interval,
        threshold,
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
