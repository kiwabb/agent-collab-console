"""Regression: CLI/cmux control envelopes (e.g. SessionStart hook lines) must
never leak into a subagent's result text or the Conductor-facing summary.

Repro: a subagent that fails before emitting real output can have the CLI echo
its hook envelope as the final `result` string, which then surfaced as the
decision-timeline dispatch summary (`{"type":"system","subtype":"hook_started",...}`).
"""

from datetime import datetime

from app.application.process_runtime_common import is_cli_control_payload
from app.application.subagent_result_builder import build_subagent_result
from app.domain.models import CodexTask, WorkflowNode

HOOK_LINE = (
    '{"type":"system","subtype":"hook_started",'
    '"hook_id":"6738ac56","hook_name":"SessionStart:resume",'
    '"hook_event":"SessionStart","session_id":"1e66361e"}'
)


def test_detects_system_hook_envelope():
    assert is_cli_control_payload(HOOK_LINE) is True
    assert is_cli_control_payload('{"hook_name":"PreToolUse"}') is True
    assert is_cli_control_payload('{"type":"system"}') is True


def test_keeps_real_output():
    assert is_cli_control_payload("Review completed: approved. Reason: ok.") is False
    # A legitimate JSON result object without system/hook markers is kept.
    assert is_cli_control_payload('{"status":"ok"}') is False
    assert is_cli_control_payload("") is False
    assert is_cli_control_payload(None) is False


def test_summary_strips_control_envelope():
    node = WorkflowNode(id="n1", graph_id="g1", node_key="START", agent_id="")
    task = CodexTask(
        id="t1",
        session_id="s1",
        title="architect review",
        prompt="review",
        issue_id="i1",
        role="architect",
        status="failed",
        result=HOOK_LINE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = build_subagent_result(task=task, node=node, doc=None)
    assert result.summary == ""


def test_summary_preserves_real_result():
    node = WorkflowNode(id="n2", graph_id="g1", node_key="START", agent_id="")
    task = CodexTask(
        id="t2",
        session_id="s1",
        title="architect review",
        prompt="review",
        issue_id="i1",
        role="architect",
        status="done",
        result="Review completed: approved.",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = build_subagent_result(task=task, node=node, doc=None)
    assert result.summary == "Review completed: approved."
