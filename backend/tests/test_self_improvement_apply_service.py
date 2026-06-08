from datetime import datetime

import pytest

from app.application.self_improvement_apply_service import (
    SelfImprovementApplyError,
    apply_project_memory_proposal,
    build_self_improvement_apply_plan,
    hash_apply_candidate_content,
)
from app.domain.models import SelfImprovementProposal


def _proposal(
    *,
    target_kind: str = "project_memory",
    status: str = "accepted",
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
        status=status,
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


def test_hash_apply_candidate_content_uses_sha256_hex():
    assert hash_apply_candidate_content("hello\n") == (
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286"
        "a2e846f6be03"
    )


def test_apply_project_memory_proposal_appends_reviewed_candidate(tmp_path):
    proposal = _proposal()
    plan = build_self_improvement_apply_plan(proposal)
    content = plan["candidate_changes"][0]["content"]
    content_hash = hash_apply_candidate_content(content)

    result = apply_project_memory_proposal(
        project_repo_path=str(tmp_path),
        proposal=proposal,
        reviewed_content_sha256=content_hash,
    )

    memory_path = tmp_path / ".agent-collab" / "team_notes.md"
    assert result.path == ".agent-collab/team_notes.md"
    assert result.content_sha256 == content_hash
    assert result.already_present is False
    assert result.bytes_written == len(content.encode("utf-8"))
    assert memory_path.read_text(encoding="utf-8") == content


def test_apply_project_memory_proposal_is_idempotent_when_marker_exists(tmp_path):
    proposal = _proposal()
    plan = build_self_improvement_apply_plan(proposal)
    content = plan["candidate_changes"][0]["content"]
    memory_path = tmp_path / ".agent-collab" / "team_notes.md"
    memory_path.parent.mkdir()
    memory_path.write_text("Existing note\n\n" + content, encoding="utf-8")

    result = apply_project_memory_proposal(
        project_repo_path=str(tmp_path),
        proposal=proposal,
        reviewed_content_sha256=hash_apply_candidate_content(content),
    )

    assert result.already_present is True
    assert result.bytes_written == 0
    assert memory_path.read_text(encoding="utf-8").count("self-improvement-proposal:proposal-1") == 1


def test_apply_project_memory_proposal_rejects_hash_mismatch_without_writing(tmp_path):
    proposal = _proposal()

    with pytest.raises(SelfImprovementApplyError) as exc:
        apply_project_memory_proposal(
            project_repo_path=str(tmp_path),
            proposal=proposal,
            reviewed_content_sha256="0" * 64,
        )

    assert exc.value.code == "hash_mismatch"
    assert not (tmp_path / ".agent-collab" / "team_notes.md").exists()


def test_apply_project_memory_proposal_rejects_non_memory_target(tmp_path):
    proposal = _proposal(target_kind="code_spec")
    content = build_self_improvement_apply_plan(proposal)["candidate_changes"][0]["body"]

    with pytest.raises(SelfImprovementApplyError) as exc:
        apply_project_memory_proposal(
            project_repo_path=str(tmp_path),
            proposal=proposal,
            reviewed_content_sha256=hash_apply_candidate_content(content),
        )

    assert exc.value.code == "unsupported_target"
    assert not (tmp_path / ".agent-collab" / "team_notes.md").exists()


def test_apply_project_memory_proposal_requires_accepted_status(tmp_path):
    proposal = _proposal(status="proposed")
    content = build_self_improvement_apply_plan(_proposal())["candidate_changes"][0]["content"]

    with pytest.raises(SelfImprovementApplyError) as exc:
        apply_project_memory_proposal(
            project_repo_path=str(tmp_path),
            proposal=proposal,
            reviewed_content_sha256=hash_apply_candidate_content(content),
        )

    assert exc.value.code == "invalid_status"
    assert not (tmp_path / ".agent-collab" / "team_notes.md").exists()


def test_apply_project_memory_proposal_requires_existing_repo_path(tmp_path):
    proposal = _proposal()
    content = build_self_improvement_apply_plan(proposal)["candidate_changes"][0]["content"]

    with pytest.raises(SelfImprovementApplyError) as exc:
        apply_project_memory_proposal(
            project_repo_path=str(tmp_path / "missing"),
            proposal=proposal,
            reviewed_content_sha256=hash_apply_candidate_content(content),
        )

    assert exc.value.code == "repo_unavailable"
