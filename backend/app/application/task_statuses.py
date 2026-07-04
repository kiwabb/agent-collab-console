from __future__ import annotations

TASK_SUCCESS_STATUSES = frozenset({"done", "completed", "success", "passed", "ok"})
TASK_PENDING_STATUS = "pending"
TASK_ACTIVE_STATUSES = frozenset({"running", "responding"})
TASK_WAITING_FOR_HELP_STATUS = "waiting_for_help"
TASK_WAITING_FOR_SPECIALIST_STATUS = "waiting_for_specialist"
TASK_FAILURE_STATUSES = frozenset(
    {
        "failed",
        "error",
        "cancelled",
        "canceled",
        "killed",
        "timeout",
        "timed_out",
        "protocol_error",
    }
)
TASK_TERMINAL_STATUSES = TASK_SUCCESS_STATUSES | TASK_FAILURE_STATUSES


def normalize_task_status(status: object | None) -> str:
    return str(status or "").strip().lower()


def is_task_active_status(status: object | None) -> bool:
    return normalize_task_status(status) in TASK_ACTIVE_STATUSES


def is_task_pending_status(status: object | None) -> bool:
    return normalize_task_status(status) == TASK_PENDING_STATUS


def is_task_waiting_for_help_status(status: object | None) -> bool:
    return normalize_task_status(status) == TASK_WAITING_FOR_HELP_STATUS


def is_task_waiting_for_specialist_status(status: object | None) -> bool:
    return normalize_task_status(status) == TASK_WAITING_FOR_SPECIALIST_STATUS


def is_task_success_status(status: object | None) -> bool:
    return normalize_task_status(status) in TASK_SUCCESS_STATUSES


def is_task_failure_status(status: object | None) -> bool:
    return normalize_task_status(status) in TASK_FAILURE_STATUSES


def is_task_terminal_status(status: object | None) -> bool:
    return normalize_task_status(status) in TASK_TERMINAL_STATUSES
