"""Conductor policy hints.

Two complementary layers (merged from two independently developed designs):
- OrchestrationPolicy: static issue-text analysis -> serial vs parallel/batch
  dispatch recommendation, embedded into the conductor prompt before a run.
- ConductorPolicyDecision: runtime evidence (recent turns / graph / budget)
  -> per-loop action decision (call_llm vs deterministic guard / finalize).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OrchestrationPolicy:
    recommendation: str
    batch_allowed: bool
    signals: tuple[str, ...]
    guidance: tuple[str, ...]


_FILE_REF_RE = re.compile(
    r"\b[\w.-]+\.(?:py|pyi|ts|tsx|js|jsx|json|md|mdx|css|scss|html|sql|yaml|yml|toml)\b",
    re.IGNORECASE,
)

_EXPLICIT_PARALLEL_PATTERNS = (
    "dispatch all",
    "dispatch_batch",
    "in parallel",
    "parallel",
    "fan out",
    "fanout",
    "concurrent",
    "same batch",
    "one batch",
)
_INDEPENDENT_PATTERNS = (
    "independent",
    "independently",
    "no cross-dependencies",
    "no cross dependencies",
    "no shared files",
    "separate files",
    "own file",
    "each file",
    "each creates one",
    "per module",
)
_TRIVIAL_PATTERNS = (
    "typo",
    "one string",
    "single string",
    "single file",
    "one file",
    "tiny",
    "trivial",
    "small fix",
    "copy change",
    "rename",
)
_AMBIGUITY_PATTERNS = (
    "figure out",
    "unclear",
    "not sure",
    "maybe",
    "decide",
    "explore",
    "research",
    "requirements unclear",
    "unclear requirements",
    "missing requirements",
    "clarify requirements",
    "define requirements",
    "what should",
    "make it better",
)
_RISK_PATTERNS = (
    "migration",
    "schema",
    "database",
    "auth",
    "authentication",
    "security",
    "public api",
    "api contract",
    "contract",
    "cross-layer",
    "cross layer",
    "architecture",
    "payment",
    "billing",
    "concurrency",
    "protocol",
    "data model",
)


def classify_issue_orchestration(title: str | None, description: str | None) -> OrchestrationPolicy:
    """Classify the safest default Conductor workflow before the LLM chooses tools."""
    text = _normalize_text(title, description)
    file_refs = _FILE_REF_RE.findall(text)
    signals: list[str] = []

    explicit_parallel = _contains_any(text, _EXPLICIT_PARALLEL_PATTERNS)
    independent_slices = _contains_any(text, _INDEPENDENT_PATTERNS) or len(file_refs) >= 3
    trivial = _contains_any(text, _TRIVIAL_PATTERNS) or (0 < len(file_refs) <= 1 and len(text) < 180)
    ambiguous = _is_ambiguous(text)
    risky = _contains_any(text, _RISK_PATTERNS) or _mentions_multiple_layers(text)

    if explicit_parallel:
        signals.append("explicit_parallel")
    if independent_slices:
        signals.append("independent_slices")
    if trivial:
        signals.append("trivial")
    if ambiguous:
        signals.append("ambiguous_scope")
    if risky:
        signals.append("risk_or_cross_layer")
    if not signals:
        signals.append("default_serial")

    if ambiguous:
        return OrchestrationPolicy(
            recommendation="pm_first",
            batch_allowed=False,
            signals=tuple(signals),
            guidance=(
                "Start with `pm` to clarify scope, acceptance criteria, and intended outcome.",
                "Do not use `dispatch_batch` until the work is decomposed into verified independent slices.",
                "Run implementation and QA only after requirements are explicit.",
            ),
        )

    if risky:
        return OrchestrationPolicy(
            recommendation="architect_first",
            batch_allowed=False,
            signals=tuple(signals),
            guidance=(
                "Start with `architect` because the issue touches risk, contracts, or multiple layers.",
                "Do not use `dispatch_batch` until the design names independent, non-overlapping workstreams.",
                "Keep QA mandatory before `finalize_task`.",
            ),
        )

    if explicit_parallel and independent_slices:
        return OrchestrationPolicy(
            recommendation="batch_allowed",
            batch_allowed=True,
            signals=tuple(signals),
            guidance=(
                "`dispatch_batch` is allowed because the issue explicitly requests parallel independent work.",
                "Keep one agent per independent slice and avoid shared-file edits inside the same batch.",
                "Run QA after the batch merge before `finalize_task`.",
            ),
        )

    if trivial:
        return OrchestrationPolicy(
            recommendation="single_engineer",
            batch_allowed=False,
            signals=tuple(signals),
            guidance=(
                "Prefer one focused `engineer` for this small, clear issue.",
                "Do not use `dispatch_batch` unless the user explicitly asks for parallel independent work.",
                "Run QA after implementation before `finalize_task`.",
            ),
        )

    return OrchestrationPolicy(
        recommendation="single_engineer",
        batch_allowed=False,
        signals=tuple(signals),
        guidance=(
            "Prefer the smallest serial workflow that can satisfy and verify the issue.",
            "Do not use `dispatch_batch` unless the issue is explicitly parallel and independently sliceable.",
            "Run QA after implementation before `finalize_task`.",
        ),
    )


def render_orchestration_policy_block(policy: OrchestrationPolicy) -> str:
    label_by_recommendation = {
        "pm_first": "PM first",
        "architect_first": "architect first",
        "batch_allowed": "batch allowed",
        "single_engineer": "single engineer",
    }
    recommendation = label_by_recommendation.get(policy.recommendation, policy.recommendation)
    signals = ", ".join(policy.signals) if policy.signals else "none"
    guidance = "\n".join(f"- {item}" for item in policy.guidance)
    return (
        "\n\n## ORCHESTRATION POLICY\n"
        f"Recommended default: {recommendation}\n"
        f"Batch allowed: {'yes' if policy.batch_allowed else 'no'}\n"
        f"Signals: {signals}\n"
        "Guidance:\n"
        f"{guidance}\n"
    )


def render_issue_orchestration_policy_block(title: str | None, description: str | None) -> str:
    return render_orchestration_policy_block(classify_issue_orchestration(title, description))


def _normalize_text(title: str | None, description: str | None) -> str:
    return " ".join(part.strip() for part in (title or "", description or "") if part and part.strip()).lower()


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if " " in pattern or "-" in pattern or "_" in pattern:
            if pattern in text:
                return True
            continue
        if re.search(rf"\b{re.escape(pattern)}\b", text):
            return True
    return False


def _is_ambiguous(text: str) -> bool:
    if not text or len(text) < 12:
        return True
    return _contains_any(text, _AMBIGUITY_PATTERNS)


def _mentions_multiple_layers(text: str) -> bool:
    layers = 0
    for layer in ("frontend", "backend", "api", "database", "db", "ui", "cli"):
        if re.search(rf"\b{re.escape(layer)}\b", text):
            layers += 1
    return layers >= 2


# ---------------------------------------------------------------------------
# Runtime per-loop policy decision (origin/main design)
# ---------------------------------------------------------------------------

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
