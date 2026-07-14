from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

PlanStatus = Literal["queued", "analyzing", "ready", "analysis_failed", "stale", "interrupted"]
PlanConfidence = Literal["high", "medium", "low"]
PlanAction = Literal["create", "update", "unchanged", "missing", "unsupported"]
PlanDiscoveryOrigin = Literal["static", "claude"]
PlanReviewStatus = Literal["provisional", "confirmed", "needs_confirmation"]
PlanOutputLocale = Literal["zh-CN", "en-US"]
PlanSelectionUpdateStatus = Literal[
    "updated",
    "plan_not_found",
    "not_editable",
    "item_not_found",
    "ineligible",
]


def empty_project_context() -> dict[str, str]:
    return {
        "product_summary": "",
        "audience": "",
        "visual_language": "",
        "shared_layout": "",
    }


@dataclass(frozen=True)
class PrototypePlanSelectionUpdate:
    status: PlanSelectionUpdateStatus
    item_ids: tuple[str, ...] = ()


@dataclass
class PrototypePlanItem:
    id: str
    plan_id: str
    candidate_id: str
    package_root: str
    surface_kind: str
    route_patterns: list[str]
    primary_source_path: str | None
    source_paths: list[str]
    layout_paths: list[str]
    title: str
    summary: str
    brief: str
    states: list[str]
    evidence_ids: list[str]
    evidence: list[dict[str, object]]
    confidence: PlanConfidence
    action: PlanAction
    selected: bool
    source_hash: str
    discovery_origin: PlanDiscoveryOrigin = "static"
    review_status: PlanReviewStatus = "confirmed"
    prototype_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def _serialized_evidence(self) -> list[dict[str, object]]:
        serialized: list[dict[str, object]] = []
        for evidence in self.evidence:
            payload = dict(evidence)
            payload.setdefault("confidence", self.confidence)
            if "diagnostic" not in payload:
                detail = payload.get("detail")
                if payload.get("kind") == "parser" and isinstance(detail, str) and detail:
                    payload["diagnostic"] = detail
                elif detail == "directory fallback":
                    payload["diagnostic"] = (
                        "route declaration was not found; directory fallback is low confidence"
                    )
                else:
                    payload["diagnostic"] = None
            serialized.append(payload)
        return serialized

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "candidate_id": self.candidate_id,
            "package_root": self.package_root,
            "surface_kind": self.surface_kind,
            "route_patterns": self.route_patterns,
            "primary_source_path": self.primary_source_path,
            "source_paths": self.source_paths,
            "layout_paths": self.layout_paths,
            "title": self.title,
            "summary": self.summary,
            "brief": self.brief,
            "states": self.states,
            "evidence_ids": self.evidence_ids,
            "evidence": self._serialized_evidence(),
            "confidence": self.confidence,
            "action": self.action,
            "selected": self.selected,
            "source_hash": self.source_hash,
            "discovery_origin": self.discovery_origin,
            "review_status": self.review_status,
            "prototype_id": self.prototype_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class PrototypePlan:
    id: str
    project_id: str
    status: PlanStatus
    repository_fingerprint: str
    scope: dict[str, object] = field(default_factory=dict)
    project_context: dict[str, str] = field(default_factory=empty_project_context)
    global_instruction: str = ""
    output_locale: PlanOutputLocale = "zh-CN"
    analysis_phase: str = "queued"
    analysis_completed: int = 0
    analysis_total: int = 0
    diagnostics: list[str] = field(default_factory=list)
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self, items: list[PrototypePlanItem] | None = None) -> dict[str, object]:
        return {
            "contract_version": 1,
            "id": self.id,
            "project_id": self.project_id,
            "status": self.status,
            "repository_fingerprint": self.repository_fingerprint,
            "scope": self.scope,
            "project_context": self.project_context,
            "global_instruction": self.global_instruction,
            "output_locale": self.output_locale,
            "analysis_phase": self.analysis_phase,
            "analysis_completed": self.analysis_completed,
            "analysis_total": self.analysis_total,
            "diagnostics": self.diagnostics,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "items": [item.to_dict() for item in items] if items is not None else [],
        }
