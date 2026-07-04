from __future__ import annotations

from app.application.conductor_main_loop import _is_conductor_success_status
from app.application.conductor_tools import _is_successful_subagent_status
from app.application.task_statuses import (
    is_task_active_status,
    is_task_failure_status,
    is_task_pending_status,
    is_task_success_status,
    is_task_terminal_status,
    is_task_waiting_for_help_status,
    is_task_waiting_for_specialist_status,
)
from app.application.workflow_scheduler import WorkflowScheduler


def test_task_terminal_statuses_cover_common_spellings():
    for status in [
        "done",
        "completed",
        "success",
        "failed",
        "error",
        "cancelled",
        "canceled",
        "killed",
        "timeout",
        "timed_out",
        "protocol_error",
    ]:
        assert is_task_terminal_status(status), status


def test_task_status_success_and_failure_are_disjoint():
    assert is_task_success_status("done")
    assert is_task_success_status("completed")
    assert is_task_success_status(" Success ")
    assert not is_task_success_status("failed")
    assert is_task_failure_status("failed")
    assert is_task_failure_status("error")
    assert is_task_failure_status(" Timeout ")
    assert is_task_failure_status("canceled")
    assert not is_task_failure_status("done")
    assert is_task_terminal_status(" Protocol_Error ")


def test_task_pending_status_covers_case_and_spaces():
    assert is_task_pending_status(" Pending ")
    assert not is_task_pending_status("running")


def test_task_active_statuses_cover_running_spellings():
    assert is_task_active_status("running")
    assert is_task_active_status("responding")
    assert is_task_active_status(" Running ")
    assert not is_task_active_status("pending")
    assert not is_task_active_status("done")


def test_task_waiting_statuses_cover_case_and_spaces():
    assert is_task_waiting_for_help_status(" Waiting_For_Help ")
    assert is_task_waiting_for_specialist_status(" Waiting_For_Specialist ")
    assert not is_task_waiting_for_help_status("waiting_for_specialist")
    assert not is_task_waiting_for_specialist_status("waiting_for_help")


def test_conductor_consumers_accept_shared_success_spellings():
    for status in ["done", "completed", "success", "passed", "ok", " OK "]:
        assert _is_conductor_success_status(status), status
        assert _is_successful_subagent_status(status), status
        assert WorkflowScheduler._task_status_to_node_status(status) == "done"


def test_workflow_scheduler_maps_shared_failures_to_failed_nodes():
    for status in [
        "failed",
        "error",
        "cancelled",
        "canceled",
        "killed",
        "timeout",
        "timed_out",
        "protocol_error",
    ]:
        assert WorkflowScheduler._task_status_to_node_status(status) == "failed"
