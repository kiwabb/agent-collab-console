from __future__ import annotations  # noqa: I001, RUF100

from datetime import datetime

from app.application.conductor_main_loop import build_issue_conductor_prompt
from app.application.conductor_policy import (
    classify_issue_orchestration,
    decide_conductor_policy,
)
from app.domain.models import CodexIssue, ConductorTask, ConductorTurn, ConductorTurnKind


def test_trivial_single_file_prefers_single_engineer():
    policy = classify_issue_orchestration(
        "Fix typo",
        "Change one string in README.md.",
    )

    assert policy.recommendation == "single_engineer"
    assert policy.batch_allowed is False
    assert "trivial" in policy.signals


def test_explicit_parallel_independent_slices_allows_batch():
    policy = classify_issue_orchestration(
        "Create three independent modules in parallel",
        "Create module_a.py, module_b.py, module_c.py. Dispatch all three engineers in parallel as one batch.",
    )

    assert policy.recommendation == "batch_allowed"
    assert policy.batch_allowed is True
    assert "explicit_parallel" in policy.signals
    assert "independent_slices" in policy.signals


def test_ambiguous_issue_recommends_pm_first():
    policy = classify_issue_orchestration(
        "Improve dashboard",
        "Figure out what should be improved and make it better.",
    )

    assert policy.recommendation == "pm_first"
    assert policy.batch_allowed is False
    assert "ambiguous_scope" in policy.signals


def test_cross_layer_issue_recommends_architect_first():
    policy = classify_issue_orchestration(
        "Change auth API contract",
        "Update the database schema, backend API contract, and frontend auth flow.",
    )

    assert policy.recommendation == "architect_first"
    assert policy.batch_allowed is False
    assert "risk_or_cross_layer" in policy.signals


def test_prompt_includes_orchestration_policy_block():
    prompt = build_issue_conductor_prompt(
        issue=CodexIssue(
            id="issue-policy-1",
            session_id="session-policy",
            title="Fix typo",
            description="Change one string in README.md.",
        ),
        project_context="",
        budget_context="",
        language_directive="",
    )

    assert "## ORCHESTRATION POLICY" in prompt
    assert "Recommended default: single engineer" in prompt
    assert "Batch allowed: no" in prompt
    assert "Do not use `dispatch_batch`" in prompt


def test_prompt_allows_batch_when_user_explicitly_requests_parallel_independent_work():
    prompt = build_issue_conductor_prompt(
        issue=CodexIssue(
            id="issue-policy-2",
            session_id="session-policy",
            title="REAL run: three tiny independent modules in parallel",
            description=(
                "Create alpha.py, beta.py, and gamma.py independently. "
                "Dispatch all three engineers in parallel as one batch."
            ),
        ),
        project_context="",
        budget_context="",
        language_directive="",
    )

    assert "## ORCHESTRATION POLICY" in prompt
    assert "Recommended default: batch allowed" in prompt
    assert "Batch allowed: yes" in prompt
    assert "explicit_parallel" in prompt
    assert "independent_slices" in prompt


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


def _turn(kind: ConductorTurnKind, payload_json: str, index: int = 0) -> ConductorTurn:
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


def test_malformed_tool_result_payload_falls_back_to_default_decision():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn("tool_result", "{not-json"),
        ],
        graph=None,
    )

    assert decision.action == "call_llm"
    assert decision.reason_code == "default_call_llm"


def test_non_object_turn_payload_falls_back_to_default_decision():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn("tool_result", '["not", "an", "object"]'),
        ],
        graph=None,
    )

    assert decision.action == "call_llm"
    assert decision.reason_code == "default_call_llm"


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


def test_repeated_success_alias_finalize_skips_llm():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn("finalize", '{"status":"completed","answer":"already complete"}', index=0),
            _turn("finalize", '{"status":"success","answer":"already complete"}', index=1),
        ],
        graph=None,
    )

    assert decision.action == "skip_llm"
    assert decision.reason_code == "recent_safe_finalize"
