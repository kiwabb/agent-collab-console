from datetime import datetime

from app.application.conductor_policy import decide_conductor_policy
from app.domain.models import CodexIssue, ConductorTask, ConductorTurn


def _issue() -> CodexIssue:
    return CodexIssue(
        id="issue-1",
        session_id="session-1",
        project_id="project-1",
        title="Add endpoint",
        description="Return JSON",
        status="in_progress",
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        updated_at=datetime(2026, 6, 8, 10, 0, 0),
    )


def _task() -> ConductorTask:
    return ConductorTask(
        id="ct-1",
        project_id="project-1",
        issue_id="issue-1",
        task_kind="issue",
        status="running",
        payload={"phase": "awaiting_llm"},
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        updated_at=datetime(2026, 6, 8, 10, 0, 0),
    )


def _turn(kind: str, payload_json: str, index: int = 0) -> ConductorTurn:
    return ConductorTurn(
        id=f"turn-{index}",
        conductor_task_id="ct-1",
        issue_id="issue-1",
        turn_index=index,
        sub_index=0,
        kind=kind,
        payload_json=payload_json,
        created_at=datetime(2026, 6, 8, 10, 0, 0),
    )


def test_first_turn_calls_llm():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[],
        graph=None,
    )

    assert decision.action == "call_llm"
    assert decision.reason_code == "first_decision"
    assert decision.prompt_hint == ""


def test_risky_tool_result_calls_llm_with_hint():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn(
                "tool_result",
                '{"name":"dispatch_subagent","result":{"status":"retries_exhausted","role":"engineer"}}',
            )
        ],
        graph=None,
    )

    assert decision.action == "call_llm"
    assert decision.reason_code == "role_retries_exhausted"
    assert "engineer" in decision.prompt_hint
    assert decision.evidence[0]["status"] == "retries_exhausted"


def test_role_busy_calls_llm_with_prompt_hint():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn(
                "tool_result",
                '{"name":"dispatch_subagent","result":{"status":"role_busy","role":"qa"}}',
            )
        ],
        graph=None,
    )

    assert decision.action == "call_llm"
    assert decision.reason_code == "role_busy"
    assert "qa" in decision.prompt_hint


def test_dispatch_batch_conflict_calls_llm_with_prompt_hint():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn(
                "tool_result",
                '{"name":"dispatch_batch","result":{"merge_status":"conflict","conflicts":[{"file":"app.py"}]}}',
            )
        ],
        graph=None,
    )

    assert decision.action == "call_llm"
    assert decision.reason_code == "dispatch_batch_conflict"
    assert "conflict" in decision.prompt_hint.lower()


def test_repeated_low_signal_finalize_skips_llm():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn("finalize", '{"status":"done","answer":"already complete"}', index=0),
            _turn("finalize", '{"status":"done","answer":"already complete"}', index=1),
        ],
        graph=None,
    )

    assert decision.action == "skip_llm"
    assert decision.reason_code == "recent_safe_finalize"
