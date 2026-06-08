from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConductorPolicyDecision:
    action: str
    reason_code: str
    reason: str
    prompt_hint: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "prompt_hint": self.prompt_hint,
            "evidence": self.evidence,
        }


def _turn_payload(turn: object) -> dict[str, Any]:
    raw = getattr(turn, "payload_json", None)
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": str(raw)}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def _tool_result_payload(turn: object) -> dict[str, Any]:
    payload = _turn_payload(turn)
    result = payload.get("result")
    if isinstance(result, dict):
        return result
    return {}


def _evidence_from_turn(turn: object, *, status: str = "", role: str = "") -> dict[str, Any]:
    return {
        "kind": "conductor_turn",
        "id": getattr(turn, "id", None),
        "turn_index": getattr(turn, "turn_index", None),
        "status": status,
        "role": role,
    }


def _done_finalize_count(recent_turns: list[object]) -> int:
    count = 0
    for turn in recent_turns[-3:]:
        if getattr(turn, "kind", "") != "finalize":
            continue
        payload = _turn_payload(turn)
        if str(payload.get("status") or "").lower() == "done":
            count += 1
    return count


def decide_conductor_policy(
    issue: object,
    conductor_task: object,
    *,
    recent_turns: list[object],
    graph: object | None,
    budget_status: object | None = None,
) -> ConductorPolicyDecision:
    if not recent_turns:
        return ConductorPolicyDecision(
            action="call_llm",
            reason_code="first_decision",
            reason="No recent conductor turns exist; the initial issue decision needs the Conductor LLM.",
        )

    for turn in reversed(recent_turns[-8:]):
        if getattr(turn, "kind", "") != "tool_result":
            continue
        result = _tool_result_payload(turn)
        status = str(result.get("status") or "").lower()
        role = str(result.get("role") or "").strip()
        merge_status = str(result.get("merge_status") or "").lower()
        if status == "retries_exhausted":
            role_label = role or "unknown"
            return ConductorPolicyDecision(
                action="call_llm",
                reason_code="role_retries_exhausted",
                reason=f"Role {role_label} exhausted its dispatch budget.",
                prompt_hint=(
                    f"Role {role_label} already exhausted its dispatch budget. "
                    "Do not redispatch it; choose a different role, ask the user, or finalize blocked work."
                ),
                evidence=[_evidence_from_turn(turn, status=status, role=role)],
            )
        if status == "role_busy":
            role_label = role or "unknown"
            return ConductorPolicyDecision(
                action="call_llm",
                reason_code="role_busy",
                reason=f"Role {role_label} is currently saturated.",
                prompt_hint=(
                    f"Role {role_label} is busy. Dispatch useful independent work first, wait and retry later, "
                    "or finalize if blocked."
                ),
                evidence=[_evidence_from_turn(turn, status=status, role=role)],
            )
        if status == "artifact_invalid":
            role_label = role or "unknown"
            return ConductorPolicyDecision(
                action="call_llm",
                reason_code="artifact_invalid",
                reason=f"Role {role_label} returned an invalid artifact.",
                prompt_hint=(
                    f"Role {role_label} returned artifact_invalid. Redispatch the same role only with a corrective "
                    "prompt that restates the required schema and validation error."
                ),
                evidence=[_evidence_from_turn(turn, status=status, role=role)],
            )
        if merge_status == "conflict":
            return ConductorPolicyDecision(
                action="call_llm",
                reason_code="dispatch_batch_conflict",
                reason="A dispatch_batch merge conflict needs deliberate reconciliation.",
                prompt_hint=(
                    "dispatch_batch returned a merge conflict. Dispatch one engineer to reconcile the conflicting "
                    "files/diffs, or ask the user if the conflict is ambiguous."
                ),
                evidence=[_evidence_from_turn(turn, status=merge_status, role=role)],
            )

    finalize_count = _done_finalize_count(recent_turns)
    if finalize_count >= 2:
        return ConductorPolicyDecision(
            action="skip_llm",
            reason_code="recent_safe_finalize",
            reason="Recent Conductor evidence already finalized successfully; avoid a redundant LLM turn.",
            evidence=[{"kind": "recent_finalize_count", "count": finalize_count}],
        )

    return ConductorPolicyDecision(
        action="call_llm",
        reason_code="default_call_llm",
        reason="No conservative skip rule matched.",
    )


def render_conductor_policy_hint(decision: ConductorPolicyDecision) -> str:
    if decision.action != "call_llm" or not decision.prompt_hint:
        return ""
    return f"\n\n## POLICY HINT\nReason: {decision.reason_code}\n{decision.prompt_hint}"
