from __future__ import annotations

from types import SimpleNamespace

from app.application.conductor_main_loop import build_issue_conductor_prompt
from app.application.conductor_policy import classify_issue_orchestration


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
        issue=SimpleNamespace(
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
        issue=SimpleNamespace(
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
