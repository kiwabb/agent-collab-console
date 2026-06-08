from __future__ import annotations

import json

from app.application.project_memory_service import MEMORY_DIR_NAME, MEMORY_FILE_NAME
from app.domain.models import SelfImprovementProposal


def _parse_evidence(evidence_json: str | None) -> list[dict]:
    try:
        parsed = json.loads(evidence_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _format_evidence_lines(evidence: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in evidence:
        kind = str(item.get("kind") or "evidence")
        pointer = item.get("path") or item.get("id") or item.get("summary") or item.get("value")
        if pointer is None:
            pointer = json.dumps(item, sort_keys=True)
        lines.append(f"- {kind}: {pointer}")
    return lines


def _project_memory_candidate(proposal: SelfImprovementProposal) -> dict:
    evidence_lines = _format_evidence_lines(_parse_evidence(proposal.evidence_json))
    content_lines = [
        f"<!-- self-improvement-proposal:{proposal.id} -->",
        f"## {proposal.title}",
        (
            f"_source issue: {proposal.issue_id} · severity: {proposal.severity} · "
            f"confidence: {proposal.confidence:.2f}_"
        ),
        "",
        proposal.recommendation.strip(),
    ]
    if evidence_lines:
        content_lines.extend(["", "**Evidence:**", *evidence_lines])
    return {
        "kind": "append_markdown",
        "path": f"{MEMORY_DIR_NAME}/{MEMORY_FILE_NAME}",
        "content": "\n".join(content_lines).rstrip() + "\n",
    }


def _pr_task_candidate(proposal: SelfImprovementProposal) -> dict:
    evidence_lines = _format_evidence_lines(_parse_evidence(proposal.evidence_json))
    body_lines = [
        f"Target kind: `{proposal.target_kind}`",
        f"Source issue: `{proposal.issue_id}`",
        f"Severity: `{proposal.severity}`",
        f"Confidence: `{proposal.confidence:.2f}`",
        "",
        proposal.recommendation.strip(),
    ]
    if evidence_lines:
        body_lines.extend(["", "Evidence:", *evidence_lines])
    return {
        "kind": "open_pr_task",
        "title": f"Apply self-improvement proposal: {proposal.title}",
        "body": "\n".join(body_lines).strip(),
    }


def build_self_improvement_apply_plan(proposal: SelfImprovementProposal) -> dict:
    """Build a dry-run application plan for an accepted self-improvement proposal."""
    if proposal.target_kind == "project_memory":
        return {
            "mode": "dry_run",
            "target_kind": proposal.target_kind,
            "can_auto_apply": False,
            "summary": "Append a reviewed lesson to project team notes.",
            "steps": [
                "Review the proposed markdown lesson.",
                "Append it to .agent-collab/team_notes.md in a separate reviewed change.",
                "Mark the proposal applied only after the reviewed change lands.",
            ],
            "candidate_changes": [_project_memory_candidate(proposal)],
            "risk": "low",
            "next_action": "review_then_apply",
        }
    return {
        "mode": "dry_run",
        "target_kind": proposal.target_kind,
        "can_auto_apply": False,
        "summary": "Open a reviewed PR/task to apply this self-improvement proposal.",
        "steps": [
            "Create a focused task or PR from the proposal recommendation.",
            "Use the evidence pointers to update the relevant spec, policy, tool, or benchmark.",
            "Run verification before marking the proposal applied.",
        ],
        "candidate_changes": [_pr_task_candidate(proposal)],
        "risk": "medium",
        "next_action": "open_reviewed_pr",
    }
