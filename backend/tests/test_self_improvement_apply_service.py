from datetime import datetime

from app.application.self_improvement_apply_service import build_self_improvement_apply_plan
from app.domain.models import SelfImprovementProposal


def _proposal(
    *,
    target_kind: str = "project_memory",
    title: str = "Remember QA command evidence",
    recommendation: str = "Record the commands QA actually ran when a bug escapes.",
    evidence_json: str = '[{"kind":"qa_report","path":"issues/issue-1/qa.json"}]',
) -> SelfImprovementProposal:
    return SelfImprovementProposal(
        id="proposal-1",
        project_id="project-1",
        issue_id="issue-1",
        target_kind=target_kind,
        title=title,
        recommendation=recommendation,
        evidence_json=evidence_json,
        severity="medium",
        confidence=0.82,
        status="accepted",
        fingerprint=f"project-1|issue-1|{target_kind}|lesson",
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        updated_at=datetime(2026, 6, 8, 10, 1, 0),
    )


def test_project_memory_apply_plan_returns_team_notes_append_candidate():
    plan = build_self_improvement_apply_plan(_proposal())

    assert plan["mode"] == "dry_run"
    assert plan["target_kind"] == "project_memory"
    assert plan["can_auto_apply"] is False
    assert plan["risk"] == "low"
    assert plan["next_action"] == "review_then_apply"
    assert plan["candidate_changes"] == [
        {
            "kind": "append_markdown",
            "path": ".agent-collab/team_notes.md",
            "content": (
                "<!-- self-improvement-proposal:proposal-1 -->\n"
                "## Remember QA command evidence\n"
                "_source issue: issue-1 · severity: medium · confidence: 0.82_\n\n"
                "Record the commands QA actually ran when a bug escapes.\n\n"
                "**Evidence:**\n"
                "- qa_report: issues/issue-1/qa.json\n"
            ),
        }
    ]
    assert "Append" in plan["summary"]
    assert any("Review" in step for step in plan["steps"])


def test_non_memory_apply_plan_returns_pr_task_candidate_not_direct_patch():
    proposal = _proposal(
        target_kind="code_spec",
        title="Capture retry contract",
        recommendation="Document the retry boundary in backend quality guidelines.",
    )

    plan = build_self_improvement_apply_plan(proposal)

    assert plan["mode"] == "dry_run"
    assert plan["target_kind"] == "code_spec"
    assert plan["can_auto_apply"] is False
    assert plan["risk"] == "medium"
    assert plan["next_action"] == "open_reviewed_pr"
    assert plan["candidate_changes"][0]["kind"] == "open_pr_task"
    assert plan["candidate_changes"][0]["title"] == "Apply self-improvement proposal: Capture retry contract"
    assert "Document the retry boundary" in plan["candidate_changes"][0]["body"]
    assert not any(change.get("kind") == "patch_file" for change in plan["candidate_changes"])
