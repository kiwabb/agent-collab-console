from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

SupportLevel = Literal["supported", "partial", "unsupported"]
SurfaceKind = Literal["web", "desktop", "browser-extension", "mobile", "unknown"]
Confidence = Literal["high", "medium", "low"]
EvidenceKind = Literal[
    "react-router-route",
    "vue-router-route",
    "file-route",
    "page-directory",
    "page-source",
    "layout",
    "style",
    "parser",
]


def source_line_count(source: str) -> int:
    """Return addressable source lines without inventing a line after a trailing newline."""
    return max(1, len(source.splitlines()))


@dataclass(frozen=True)
class EvidenceLocation:
    """A bounded, user-visible reference to source evidence."""

    path: str
    start_line: int
    end_line: int
    kind: EvidenceKind
    detail: str = ""
    content: str = ""
    confidence: Confidence = "high"
    diagnostic: str | None = None

    @property
    def evidence_id(self) -> str:
        value = f"{self.path}|{self.start_line}|{self.end_line}|{self.kind}|{self.detail}"
        return "evidence--" + hashlib.sha256(value.encode()).hexdigest()[:20]

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "kind": self.kind,
            "detail": self.detail,
            "content": self.content,
            "confidence": self.confidence,
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True)
class PackageSurface:
    """A package discovered inside a repository."""

    package_root: str
    manifest_path: str
    name: str
    framework_signals: tuple[str, ...] = ()
    surface_kind: SurfaceKind = "unknown"
    support: SupportLevel = "unsupported"
    entry_candidates: tuple[str, ...] = ()
    style_candidates: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "package_root": self.package_root,
            "manifest_path": self.manifest_path,
            "name": self.name,
            "framework_signals": list(self.framework_signals),
            "surface_kind": self.surface_kind,
            "support": self.support,
            "entry_candidates": list(self.entry_candidates),
            "style_candidates": list(self.style_candidates),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class PrototypeCandidate:
    """One logical UI page family discovered from deterministic evidence."""

    candidate_id: str
    title: str
    route_patterns: tuple[str, ...]
    surface_kind: SurfaceKind
    package_root: str
    framework_hint: str
    primary_source_path: str | None
    source_paths: tuple[str, ...]
    layout_paths: tuple[str, ...]
    evidence: tuple[EvidenceLocation, ...]
    confidence: Confidence
    source_hash: str
    states: tuple[str, ...] = ("default",)
    diagnostics: tuple[str, ...] = ()
    action: str = "create"

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "route_patterns": list(self.route_patterns),
            "surface_kind": self.surface_kind,
            "package_root": self.package_root,
            "framework_hint": self.framework_hint,
            "primary_source_path": self.primary_source_path,
            "source_paths": list(self.source_paths),
            "layout_paths": list(self.layout_paths),
            "evidence": [item.to_dict() for item in self.evidence],
            "confidence": self.confidence,
            "source_hash": self.source_hash,
            "states": list(self.states),
            "diagnostics": list(self.diagnostics),
            "action": self.action,
        }


@dataclass(frozen=True)
class ProjectSurfaceManifest:
    """Complete deterministic output consumed by the planning layer."""

    repository_root: str
    packages: tuple[PackageSurface, ...]
    candidates: tuple[PrototypeCandidate, ...]
    diagnostics: tuple[str, ...] = field(default_factory=tuple)
    repository_fingerprint: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_root": self.repository_root,
            "packages": [item.to_dict() for item in self.packages],
            "candidates": [item.to_dict() for item in self.candidates],
            "diagnostics": list(self.diagnostics),
            "repository_fingerprint": self.repository_fingerprint,
        }
