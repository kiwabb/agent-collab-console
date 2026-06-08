from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.domain.models import CodexIssue, SelfImprovementProposal

logger = logging.getLogger(__name__)


class _ProposalStore(Protocol):
    async def list_conductor_tasks(self, *, status: str | None = None) -> list[object]:
        ...

    async def save_self_improvement_proposal(self, proposal: SelfImprovementProposal) -> None:
        ...


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
    return "|".join([issue.project_id or "", issue.id, target_kind, _normalize_fingerprint_part(rule_id)])


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


def _task_matches_issue(task: object, issue_id: str) -> bool:
    return getattr(task, "issue_id", None) == issue_id


async def _load_issue_tasks(issue: CodexIssue, store: _ProposalStore) -> list[object]:
    try:
        tasks = await store.list_conductor_tasks()
    except TypeError:
        tasks = []
        for status in ("failed", "stalled", "done"):
            try:
                tasks.extend(await store.list_conductor_tasks(status=status))
            except Exception as exc:  # noqa: BLE001
                logger.debug("self_improvement task read failed for %s/%s: %s", issue.id, status, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("self_improvement task read failed for %s: %s", issue.id, exc)
        return []
    return [task for task in tasks if _task_matches_issue(task, issue.id)]


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


def _task_result_object(task: object) -> dict[str, object]:
    raw = getattr(task, "result_json", None)
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _iter_tool_event_results(task: object) -> list[tuple[dict[str, object], dict[str, object]]]:
    result = _task_result_object(task)
    raw_events = result.get("tool_events")
    if not isinstance(raw_events, list):
        return []
    events: list[tuple[dict[str, object], dict[str, object]]] = []
    for raw in raw_events:
        if not isinstance(raw, dict):
            continue
        raw_result = raw.get("result")
        if not isinstance(raw_result, dict):
            continue
        events.append((raw, raw_result))
    return events


def _conductor_policy_candidate(
    task: object,
    event: dict[str, object],
    result: dict[str, object],
) -> tuple[str, str, str] | None:
    status = str(result.get("status") or "").lower()
    merge_status = str(result.get("merge_status") or "").lower()
    role = str(result.get("role") or "").strip() or "unknown"
    if status == "retries_exhausted":
        return (
            "role_retries_exhausted",
            "Capture conductor redispatch exhaustion as policy evidence",
            f"Role {role} exhausted its dispatch budget; review Conductor policy so future loops choose a different role, ask the user, or finalize blocked work.",
        )
    if status == "role_busy":
        return (
            "role_busy",
            "Capture conductor role-busy loop as policy evidence",
            f"Role {role} was saturated; review Conductor policy for useful alternate work, bounded waits, or blocked finalization.",
        )
    if status == "artifact_invalid":
        return (
            "artifact_invalid",
            "Capture invalid artifact loop as policy evidence",
            f"Role {role} returned artifact_invalid; review Conductor policy for corrective redispatch prompts and schema reminders.",
        )
    if merge_status == "conflict":
        return (
            "dispatch_batch_conflict",
            "Capture dispatch batch conflict as policy evidence",
            "A dispatch_batch merge conflict occurred; review Conductor policy for fan-out gating and single-engineer reconciliation.",
        )
    return None


def _classify_tasks(issue: CodexIssue, tasks: list[object]) -> list[SelfImprovementProposal]:
    proposals: dict[str, SelfImprovementProposal] = {}
    for task in tasks:
        for event, result in _iter_tool_event_results(task):
            candidate = _conductor_policy_candidate(task, event, result)
            if candidate is None:
                continue
            rule_id, title, recommendation = candidate
            proposal = _proposal(
                issue,
                target_kind="conductor_policy",
                rule_id=rule_id,
                title=title,
                recommendation=recommendation,
                evidence=[
                    {
                        **_task_evidence(task, rule_id),
                        "tool_event": event,
                    }
                ],
                severity="medium",
                confidence=0.78,
            )
            proposals[proposal.fingerprint] = proposal
        text = _task_result_text(task)
        status = str(getattr(task, "status", "") or "").lower()
        lowered = text.lower()
        if "qa" in lowered and ("failed" in lowered or "bugs_found" in lowered or "exit_code" in lowered):
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
    return list(proposals.values())


async def extract_self_improvement_proposals(issue: CodexIssue, store: _ProposalStore) -> list[SelfImprovementProposal]:
    if not issue.project_id:
        return []
    tasks = await _load_issue_tasks(issue, store)
    proposals = _classify_tasks(issue, tasks)
    saved: list[SelfImprovementProposal] = []
    for proposal in proposals:
        try:
            await store.save_self_improvement_proposal(proposal)
        except Exception as exc:  # noqa: BLE001
            logger.warning("self_improvement proposal save failed for issue %s: %s", issue.id, exc)
            return []
        saved.append(proposal)
    return saved


async def record_issue_self_improvement(issue: CodexIssue, store: _ProposalStore) -> list[SelfImprovementProposal]:
    try:
        return await extract_self_improvement_proposals(issue, store)
    except Exception as exc:  # noqa: BLE001
        logger.warning("self_improvement extraction failed for issue %s: %s", issue.id, exc)
        return []
