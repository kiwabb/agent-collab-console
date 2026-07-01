"""Regression: CLI/cmux control envelopes (e.g. SessionStart hook lines) must
never leak into a subagent's result text or the Conductor-facing summary.

Repro: a subagent that fails before emitting real output can have the CLI echo
its hook envelope as the final `result` string, which then surfaced as the
decision-timeline dispatch summary (`{"type":"system","subtype":"hook_started",...}`).
"""

from datetime import datetime

from app.application.process_runtime_common import (
    is_cli_control_payload,
    is_codex_protocol_frame,
    is_unusable_result_text,
)
from app.application.subagent_result_builder import build_subagent_result
from app.domain.models import CodexTask, WorkflowNode

HOOK_LINE = (
    '{"type":"system","subtype":"hook_started",'
    '"hook_id":"6738ac56","hook_name":"SessionStart:resume",'
    '"hook_event":"SessionStart","session_id":"1e66361e"}'
)

# A raw codex app-server JSON-RPC frame — codex streams its answer as thousands
# of these; an interrupted turn can leave one as result_text.
CODEX_DELTA_FRAME = (
    '{"method":"item/agentMessage/delta","params":{"threadId":"019e5d8f",'
    '"turnId":"019e5d8f-449d","itemId":"msg_0416","delta":"/api"}}'
)
CODEX_REASONING_FRAME = (
    '{"method":"item/completed","params":{"item":{"type":"reasoning",'
    '"id":"rs_04","summary":[],"content":[]},"threadId":"019e5d95"}}'
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


def test_detects_codex_protocol_frame():
    assert is_codex_protocol_frame(CODEX_DELTA_FRAME) is True
    assert is_codex_protocol_frame(CODEX_REASONING_FRAME) is True
    # method without params still counts when path-segmented (codex style).
    assert is_codex_protocol_frame('{"method":"turn/completed"}') is True


def test_codex_frame_check_keeps_real_artifacts():
    # Real role-artifact JSON has no top-level "method" — must be kept.
    assert is_codex_protocol_frame('{"status":"completed","changed_files":[]}') is False
    assert is_codex_protocol_frame('{"language":"zh-CN","product_goals":[]}') is False
    assert is_codex_protocol_frame("当前任务已经完成：实现了 /api/codex/ping。") is False  # noqa: RUF001
    assert is_codex_protocol_frame("") is False
    assert is_codex_protocol_frame(None) is False
    # A non-codex JSON-RPC-ish method name without a path segment is not a codex frame.
    assert is_codex_protocol_frame('{"method":"localcall"}') is False


def test_unusable_result_text_combines_both():
    assert is_unusable_result_text(HOOK_LINE) is True
    assert is_unusable_result_text(CODEX_DELTA_FRAME) is True
    assert is_unusable_result_text("Review completed: approved.") is False
    assert is_unusable_result_text('{"status":"ok"}') is False


def test_summary_strips_codex_protocol_frame():
    node = WorkflowNode(id="n3", graph_id="g1", node_key="START", agent_id="")
    task = CodexTask(
        id="t3",
        session_id="s1",
        title="engineer impl",
        prompt="implement",
        issue_id="i1",
        role="engineer",
        status="done",
        result=CODEX_DELTA_FRAME,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = build_subagent_result(task=task, node=node, doc=None)
    assert result.summary == ""


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
