from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.domain.models import CodexIssue, SelfImprovementProposal
from app.json_safety import object_dict, object_dict_list, parse_json_value

logger = logging.getLogger(__name__)


class _ProposalStore(Protocol):
    async def list_conductor_tasks(
        self,
        *,
        status: str | None = None,
        issue_id: str | None = None,
    ) -> list[object]: ...

    async def save_self_improvement_proposal(self, proposal: SelfImprovementProposal) -> None: ...


def _json_text(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _normalize_fingerprint_part(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "proposal"


def _fingerprint(issue: CodexIssue, target_kind: str, rule_id: str) -> str:
    return "|".join(
        [issue.project_id or "", issue.id, target_kind, _normalize_fingerprint_part(rule_id)]
    )


def _proposal(
    issue: CodexIssue,
    *,
    target_kind: str,
    rule_id: str,
    title: str,
    recommendation: str,
    evidence: list[dict[str, object]],
    severity: str = "medium",
    confidence: float = 0.75,
) -> SelfImprovementProposal:
    now = datetime.now()
    return SelfImprovementProposal(
        id=f"sip-{uuid4().hex}",
        project_id=issue.project_id or "",
        issue_id=issue.id,
        target_kind=target_kind,
        title=title,
        recommendation=recommendation,
        evidence_json=json.dumps(evidence, ensure_ascii=False, default=str),
        severity=severity,
        confidence=confidence,
        status="proposed",
        fingerprint=_fingerprint(issue, target_kind, rule_id),
        created_at=now,
        updated_at=now,
    )


async def _load_issue_tasks(issue: CodexIssue, store: _ProposalStore) -> list[object]:
    return await store.list_conductor_tasks(issue_id=issue.id)


def _task_evidence(task: object, reason: str) -> dict[str, object]:
    return {
        "kind": "conductor_task",
        "id": getattr(task, "id", None),
        "status": getattr(task, "status", None),
        "reason": reason,
        "payload": getattr(task, "payload", None),
        "result_json": getattr(task, "result_json", None),
    }


def _task_result_text(task: object) -> str:
    return _json_text(getattr(task, "result_json", None))


def _task_result_object(task: object) -> object:
    raw = getattr(task, "result_json", None)
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        return parse_json_value(raw, default=raw)
    return raw


def _issue_evidence(issue: CodexIssue, reason: str) -> dict[str, object]:
    return {
        "kind": "codex_issue",
        "id": issue.id,
        "project_id": issue.project_id,
        "title": issue.title,
        "description": issue.description,
        "status": issue.status,
        "reason": reason,
    }


def _contains_capability_signal(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "swe-bench",
            "swebench",
            "solve rate",
            "solve-rate",
            "capability",
            "autonomy",
            "benchmark",
        )
    )


def _contains_eval_evidence(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "benchmark_run",
            "pass_at_1",
            "pass@1",
            "eval_result",
            "evaluation_result",
        )
    )


def _iter_tool_events(result: object) -> list[dict[str, object]]:
    events = object_dict(result).get("tool_events")
    return object_dict_list(events)


def _classify_tasks(issue: CodexIssue, tasks: list[object]) -> list[SelfImprovementProposal]:
    proposals: dict[str, SelfImprovementProposal] = {}
    issue_text = _json_text({"title": issue.title, "description": issue.description})
    capability_signal = _contains_capability_signal(issue_text)
    has_eval_evidence = _contains_eval_evidence(issue_text)
    for task in tasks:
        text = _task_result_text(task)
        result_obj = _task_result_object(task)
        status = str(getattr(task, "status", "") or "").lower()
        lowered = text.lower()
        capability_signal = capability_signal or _contains_capability_signal(text)
        has_eval_evidence = has_eval_evidence or _contains_eval_evidence(text)
        if "qa" in lowered and (
            "failed" in lowered or "bugs_found" in lowered or "exit_code" in lowered
        ):
            proposal = _proposal(
                issue,
                target_kind="code_spec",
                rule_id="qa_failure_contract",
                title="Capture QA failure as an executable contract",
                recommendation=(
                    "Review the QA failure evidence and add or update the relevant code-spec "
                    "contract before similar issues repeat."
                ),
                evidence=[_task_evidence(task, "qa_failure")],
                severity="medium",
                confidence=0.8,
            )
            proposals[proposal.fingerprint] = proposal
        elif status in {"failed", "stalled"} or "traceback" in lowered or "runtimeerror" in lowered:
            proposal = _proposal(
                issue,
                target_kind="runtime_tooling",
                rule_id="runtime_failure_contract",
                title="Harden runtime failure handling from conductor evidence",
                recommendation=(
                    "Review the runtime/conductor failure and add a durable guard, test, "
                    "or recovery contract for this failure mode."
                ),
                evidence=[_task_evidence(task, "runtime_failure")],
                severity="medium",
                confidence=0.75,
            )
            proposals[proposal.fingerprint] = proposal
        for event in _iter_tool_events(result_obj):
            tool_result = event.get("result")
            if not isinstance(tool_result, dict):
                continue
            result_status = str(tool_result.get("status") or "").lower()
            if result_status == "retries_exhausted":
                proposal = _proposal(
                    issue,
                    target_kind="conductor_policy",
                    rule_id="role_retries_exhausted",
                    title="Review conductor redispatch budget policy",
                    recommendation=(
                        "Review the conductor policy for repeated role dispatches and capture a "
                        "clear recovery rule for exhausted retries."
                    ),
                    evidence=[_task_evidence(task, "role_retries_exhausted")],
                    severity="medium",
                    confidence=0.8,
                )
                proposals[proposal.fingerprint] = proposal
            elif result_status == "role_busy":
                proposal = _proposal(
                    issue,
                    target_kind="conductor_policy",
                    rule_id="role_busy",
                    title="Review conductor role-busy recovery policy",
                    recommendation=(
                        "Capture how the conductor should react when a role concurrency slot is "
                        "busy instead of repeatedly dispatching the same role."
                    ),
                    evidence=[_task_evidence(task, "role_busy")],
                    severity="medium",
                    confidence=0.8,
                )
                proposals[proposal.fingerprint] = proposal
            if (
                str(event.get("name") or "") == "dispatch_batch"
                and str(tool_result.get("merge_status") or "").lower() == "conflict"
            ):
                proposal = _proposal(
                    issue,
                    target_kind="conductor_policy",
                    rule_id="dispatch_batch_conflict",
                    title="Review dispatch_batch conflict recovery policy",
                    recommendation=(
                        "Capture the dispatch_batch merge-conflict recovery path as conductor "
                        "policy so future batches reconcile instead of looping."
                    ),
                    evidence=[_task_evidence(task, "dispatch_batch_conflict")],
                    severity="medium",
                    confidence=0.8,
                )
                proposals[proposal.fingerprint] = proposal
    if capability_signal and not has_eval_evidence:
        evidence = [_issue_evidence(issue, "missing_capability_eval")]
        if tasks:
            evidence.append(_task_evidence(tasks[0], "missing_capability_eval"))
        proposal = _proposal(
            issue,
            target_kind="benchmark_eval",
            rule_id="missing_capability_eval_contract",
            title="Attach benchmark evaluation to capability work",
            recommendation=(
                "Capability or autonomy improvements should include a reviewed benchmark/eval "
                "artifact before being treated as measured progress."
            ),
            evidence=evidence,
            severity="medium",
            confidence=0.75,
        )
        proposals[proposal.fingerprint] = proposal
    return list(proposals.values())


async def extract_self_improvement_proposals(
    issue: CodexIssue, store: _ProposalStore
) -> list[SelfImprovementProposal]:
    if not issue.project_id:
        return []
    tasks = await _load_issue_tasks(issue, store)
    proposals = _classify_tasks(issue, tasks)
    saved: list[SelfImprovementProposal] = []
    for proposal in proposals:
        try:
            await store.save_self_improvement_proposal(proposal)
        except Exception as exc:
            logger.warning("self_improvement proposal save failed for issue %s: %s", issue.id, exc)
            return []
        saved.append(proposal)
    return saved


async def record_issue_self_improvement(
    issue: CodexIssue, store: _ProposalStore
) -> list[SelfImprovementProposal]:
    try:
        return await extract_self_improvement_proposals(issue, store)
    except Exception as exc:
        logger.warning("self_improvement extraction failed for issue %s: %s", issue.id, exc)
        return []
