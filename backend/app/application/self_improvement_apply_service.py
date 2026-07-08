from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypedDict

from app.application.project_memory_service import MEMORY_DIR_NAME, MEMORY_FILE_NAME, project_memory
from app.domain.models import SelfImprovementProposal
from app.json_safety import parse_json_object_list


class SelfImprovementApplyError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class SelfImprovementApplyResult:
    path: str
    content_sha256: str
    already_present: bool
    bytes_written: int

    def to_dict(self) -> dict[str, str | bool | int]:
        return {
            "path": self.path,
            "content_sha256": self.content_sha256,
            "already_present": self.already_present,
            "bytes_written": self.bytes_written,
        }


@dataclass(frozen=True)
class SelfImprovementRollbackResult:
    path: str
    content_sha256: str | None
    already_absent: bool
    bytes_written: int

    def to_dict(self) -> dict[str, str | bool | int | None]:
        return {
            "path": self.path,
            "content_sha256": self.content_sha256,
            "already_absent": self.already_absent,
            "bytes_written": self.bytes_written,
        }


EvidenceItem = dict[str, object]


class AppendMarkdownCandidate(TypedDict):
    kind: Literal["append_markdown"]
    path: str
    content: str


class OpenPrTaskCandidate(TypedDict):
    kind: Literal["open_pr_task"]
    title: str
    body: str


CandidateChange = AppendMarkdownCandidate | OpenPrTaskCandidate


class ApplyPlan(TypedDict):
    mode: Literal["dry_run"]
    target_kind: str
    can_auto_apply: bool
    summary: str
    steps: list[str]
    candidate_changes: list[CandidateChange]
    risk: Literal["low", "medium"]
    next_action: Literal["review_then_apply", "open_reviewed_pr"]


def _parse_evidence(evidence_json: str | None) -> list[EvidenceItem]:
    return parse_json_object_list(evidence_json or "[]")


def _format_evidence_lines(evidence: Sequence[Mapping[str, object]]) -> list[str]:
    lines: list[str] = []
    for item in evidence:
        kind = str(item.get("kind") or "evidence")
        pointer = item.get("path") or item.get("id") or item.get("summary") or item.get("value")
        if pointer is None:
            pointer = json.dumps(item, sort_keys=True)
        lines.append(f"- {kind}: {pointer}")
    return lines


def _project_memory_candidate(proposal: SelfImprovementProposal) -> AppendMarkdownCandidate:
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


def _pr_task_candidate(proposal: SelfImprovementProposal) -> OpenPrTaskCandidate:
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


def build_self_improvement_apply_plan(proposal: SelfImprovementProposal) -> ApplyPlan:
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


def hash_apply_candidate_content(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _project_memory_append_candidate(proposal: SelfImprovementProposal) -> tuple[str, str]:
    plan = build_self_improvement_apply_plan(proposal)
    candidate_changes = plan["candidate_changes"]
    if len(candidate_changes) != 1:
        raise SelfImprovementApplyError(
            "Self-improvement apply plan must contain exactly one project-memory candidate",
            code="invalid_plan",
        )
    candidate = candidate_changes[0]
    if candidate["kind"] != "append_markdown":
        raise SelfImprovementApplyError(
            "Self-improvement apply plan does not contain a project-memory append candidate",
            code="invalid_plan",
        )
    expected_path = f"{MEMORY_DIR_NAME}/{MEMORY_FILE_NAME}"
    content = candidate["content"]
    if candidate["path"] != expected_path:
        raise SelfImprovementApplyError(
            "Self-improvement apply plan project-memory candidate is invalid",
            code="invalid_plan",
        )
    return expected_path, content


def _join_memory_sections(*sections: str) -> str:
    pieces = [section.strip() for section in sections if section.strip()]
    if not pieces:
        return ""
    return "\n\n".join(pieces) + "\n"


def _proposal_block_bounds(existing: str, marker: str) -> tuple[int, int] | None:
    start = existing.find(marker)
    if start < 0:
        return None
    search_start = start + len(marker)
    next_markers = [
        index
        for index in (
            existing.find("<!-- self-improvement-proposal:", search_start),
            existing.find("<!-- issue:", search_start),
        )
        if index >= 0
    ]
    end = min(next_markers) if next_markers else len(existing)
    return start, end


def apply_project_memory_proposal(
    *,
    project_repo_path: str | None,
    proposal: SelfImprovementProposal,
    reviewed_content_sha256: str,
) -> SelfImprovementApplyResult:
    if proposal.status != "accepted":
        raise SelfImprovementApplyError(
            "Self-improvement proposal must be accepted before it can be applied",
            code="invalid_status",
        )
    if proposal.target_kind != "project_memory":
        raise SelfImprovementApplyError(
            "Only project_memory self-improvement proposals can be applied directly",
            code="unsupported_target",
        )

    candidate_path, content = _project_memory_append_candidate(proposal)
    content_sha256 = hash_apply_candidate_content(content)
    if reviewed_content_sha256 != content_sha256:
        raise SelfImprovementApplyError(
            "Reviewed content hash does not match the current self-improvement apply plan",
            code="hash_mismatch",
        )

    if not project_repo_path:
        raise SelfImprovementApplyError(
            "Project repository path is unavailable for self-improvement application",
            code="repo_unavailable",
        )
    repo_path = Path(project_repo_path)
    if not repo_path.exists():
        raise SelfImprovementApplyError(
            "Project repository path is unavailable for self-improvement application",
            code="repo_unavailable",
        )

    memory_path = repo_path / MEMORY_DIR_NAME / MEMORY_FILE_NAME
    marker = f"<!-- self-improvement-proposal:{proposal.id} -->"
    try:
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        existing = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
    except OSError as exc:
        raise SelfImprovementApplyError(
            "Project memory file is unavailable for self-improvement application",
            code="repo_unavailable",
        ) from exc

    if marker in existing:
        return SelfImprovementApplyResult(
            path=candidate_path,
            content_sha256=content_sha256,
            already_present=True,
            bytes_written=0,
        )

    combined = (existing.rstrip() + "\n\n" + content.rstrip()).strip() + "\n"
    combined = project_memory.trim_to_cap(combined)
    try:
        memory_path.write_text(combined, encoding="utf-8")
    except OSError as exc:
        raise SelfImprovementApplyError(
            "Project memory file is unavailable for self-improvement application",
            code="repo_unavailable",
        ) from exc

    return SelfImprovementApplyResult(
        path=candidate_path,
        content_sha256=content_sha256,
        already_present=False,
        bytes_written=len(content.encode("utf-8")),
    )


def rollback_project_memory_proposal(
    *,
    project_repo_path: str | None,
    proposal: SelfImprovementProposal,
) -> SelfImprovementRollbackResult:
    if proposal.status != "applied":
        raise SelfImprovementApplyError(
            "Self-improvement proposal must be applied before it can be rolled back",
            code="invalid_status",
        )
    if proposal.target_kind != "project_memory":
        raise SelfImprovementApplyError(
            "Only project_memory self-improvement proposals can be rolled back directly",
            code="unsupported_target",
        )

    candidate_path = f"{MEMORY_DIR_NAME}/{MEMORY_FILE_NAME}"
    if not project_repo_path:
        raise SelfImprovementApplyError(
            "Project repository path is unavailable for self-improvement rollback",
            code="repo_unavailable",
        )
    repo_path = Path(project_repo_path)
    if not repo_path.exists():
        raise SelfImprovementApplyError(
            "Project repository path is unavailable for self-improvement rollback",
            code="repo_unavailable",
        )

    memory_path = repo_path / MEMORY_DIR_NAME / MEMORY_FILE_NAME
    marker = f"<!-- self-improvement-proposal:{proposal.id} -->"
    try:
        existing = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
    except OSError as exc:
        raise SelfImprovementApplyError(
            "Project memory file is unavailable for self-improvement rollback",
            code="repo_unavailable",
        ) from exc

    bounds = _proposal_block_bounds(existing, marker)
    if bounds is None:
        return SelfImprovementRollbackResult(
            path=candidate_path,
            content_sha256=None,
            already_absent=True,
            bytes_written=0,
        )

    start, end = bounds
    removed_content = existing[start:end].strip("\n") + "\n"
    combined = _join_memory_sections(existing[:start], existing[end:])
    try:
        memory_path.write_text(combined, encoding="utf-8")
    except OSError as exc:
        raise SelfImprovementApplyError(
            "Project memory file is unavailable for self-improvement rollback",
            code="repo_unavailable",
        ) from exc

    return SelfImprovementRollbackResult(
        path=candidate_path,
        content_sha256=hash_apply_candidate_content(removed_content),
        already_absent=False,
        bytes_written=len(removed_content.encode("utf-8")),
    )
