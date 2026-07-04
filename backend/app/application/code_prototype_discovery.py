from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.models import Project

IGNORED_DIRS = {
    ".agent-collab",
    ".git",
    ".next",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "tmp",
}

MAX_FILE_BYTES = 80_000
MAX_EXCERPT_CHARS = 4_000


@dataclass(frozen=True)
class CodePrototypeCandidate:
    id: str
    title: str
    route: str
    kind: str
    framework_hint: str
    source_paths: list[str]
    primary_source_path: str
    source_hash: str
    source_excerpt: str
    signals: list[str] = field(default_factory=list)
    unsupported_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "route": self.route,
            "kind": self.kind,
            "framework_hint": self.framework_hint,
            "source_paths": self.source_paths,
            "primary_source_path": self.primary_source_path,
            "source_hash": self.source_hash,
            "source_excerpt": self.source_excerpt,
            "signals": self.signals,
            "unsupported_reason": self.unsupported_reason,
        }


class CodePrototypeDiscoveryService:
    """Discover source files that can seed one HTML prototype each."""

    def scan_project(self, project: Project) -> list[CodePrototypeCandidate]:
        root = Path(project.repo_path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return []
        candidates: dict[str, CodePrototypeCandidate] = {}
        for path in sorted(self._iter_source_files(root)):
            rel = path.relative_to(root).as_posix()
            match = self._classify(rel)
            if match is None:
                continue
            route, kind, framework_hint, signals = match
            content = self._read_text(path)
            source_hash = self._hash_source(rel, content)
            title = self._derive_title(rel, route, content)
            candidate_id = self._stable_id(framework_hint, route, rel)
            candidates[candidate_id] = CodePrototypeCandidate(
                id=candidate_id,
                title=title,
                route=route,
                kind=kind,
                framework_hint=framework_hint,
                source_paths=[rel],
                primary_source_path=rel,
                source_hash=source_hash,
                source_excerpt=content[:MAX_EXCERPT_CHARS],
                signals=signals,
            )
        return list(candidates.values())

    def _iter_source_files(self, root: Path):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".tsx", ".jsx"}:
                continue
            parts = set(path.relative_to(root).parts)
            if parts & IGNORED_DIRS:
                continue
            yield path

    def _classify(self, rel: str) -> tuple[str, str, str, list[str]] | None:
        if rel.startswith("app/") and (
            rel.endswith("/page.tsx") or rel.endswith("/page.jsx")
        ):
            return (
                self._next_app_route(rel, "app"),
                "page",
                "next-app-router",
                ["app-router-page"],
            )
        for prefix in ("src/app", "frontend/src/app"):
            if rel.startswith(f"{prefix}/") and (
                rel.endswith("/page.tsx") or rel.endswith("/page.jsx")
            ):
                return (
                    self._next_app_route(rel, prefix),
                    "page",
                    "next-app-router",
                    ["app-router-page"],
                )
        for prefix in ("pages", "src/pages"):
            if rel.startswith(f"{prefix}/") and rel.endswith((".tsx", ".jsx")):
                route = self._pages_route(rel, prefix)
                if route is None:
                    return None
                return (route, "page", "next-pages-router", ["pages-router-page"])
        for prefix in ("src/routes", "src/pages"):
            if rel.startswith(f"{prefix}/") and rel.endswith((".tsx", ".jsx")):
                return (
                    self._generic_route(rel, prefix),
                    "route",
                    "react-routes",
                    ["route-like-file"],
                )
        if rel.startswith("src/features/") and rel.endswith((".tsx", ".jsx")):
            stem = Path(rel).stem
            if stem.endswith("Page") or stem.endswith("RoutePage"):
                return (
                    self._feature_route(rel),
                    "feature",
                    "react-feature-page",
                    ["feature-page-component"],
                )
        return None

    def _next_app_route(self, rel: str, prefix: str) -> str:
        suffix = rel.removeprefix(f"{prefix}/")
        segments = suffix.split("/")[:-1]
        return self._route_from_segments(segments)

    def _pages_route(self, rel: str, prefix: str) -> str | None:
        suffix = rel.removeprefix(f"{prefix}/")
        if suffix.startswith("api/"):
            return None
        stem = suffix.rsplit(".", 1)[0]
        if stem in {"_app", "_document", "_error"} or stem.endswith(
            ("/_app", "/_document", "/_error")
        ):
            return None
        segments = [part for part in stem.split("/") if part != "index"]
        return self._route_from_segments(segments)

    def _generic_route(self, rel: str, prefix: str) -> str:
        stem = rel.removeprefix(f"{prefix}/").rsplit(".", 1)[0]
        segments = [part for part in stem.split("/") if part != "index"]
        return self._route_from_segments(segments)

    def _feature_route(self, rel: str) -> str:
        stem = rel.removeprefix("src/features/").rsplit(".", 1)[0]
        stem = re.sub(r"(RoutePage|Page)$", "", stem)
        segments = [self._kebab(part) for part in stem.split("/") if part]
        return self._route_from_segments(segments)

    def _route_from_segments(self, segments: list[str]) -> str:
        visible: list[str] = []
        for segment in segments:
            if segment.startswith("(") and segment.endswith(")"):
                continue
            if segment.startswith("[[...") and segment.endswith("]]"):
                visible.append(f":{segment[5:-2]}*")
            elif segment.startswith("[...") and segment.endswith("]"):
                visible.append(f":{segment[4:-1]}*")
            elif segment.startswith("[") and segment.endswith("]"):
                visible.append(f":{segment[1:-1]}")
            else:
                visible.append(segment)
        return "/" + "/".join(visible) if visible else "/"

    def _derive_title(self, rel: str, route: str, content: str) -> str:
        for pattern in (
            r"export\s+default\s+function\s+([A-Z][A-Za-z0-9_]*)",
            r"function\s+([A-Z][A-Za-z0-9_]*)",
            r"const\s+([A-Z][A-Za-z0-9_]*)\s*=",
        ):
            match = re.search(pattern, content)
            if match:
                return self._humanize(match.group(1))
        route_title = route.strip("/").replace(":", "").replace("/", " ")
        if route_title:
            return self._humanize(route_title)
        return self._humanize(Path(rel).parent.name or "Home")

    def _read_text(self, path: Path) -> str:
        data = path.read_bytes()[:MAX_FILE_BYTES]
        return data.decode("utf-8", errors="replace")

    def _hash_source(self, rel: str, content: str) -> str:
        normalized = "\n".join(line.rstrip() for line in content.splitlines())
        digest = hashlib.sha256(f"{rel}\n{normalized}".encode()).hexdigest()
        return f"sha256:{digest}"

    def _stable_id(self, framework_hint: str, route: str, rel: str) -> str:
        slug = route.strip("/") or "home"
        slug = slug.replace(":", "").replace("*", "star")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-").lower()
        if not slug:
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", rel).strip("-").lower()
        return f"{framework_hint}--{slug}"

    def _humanize(self, value: str) -> str:
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        value = value.replace("-", " ").replace("_", " ")
        return " ".join(part.capitalize() for part in value.split())

    def _kebab(self, value: str) -> str:
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
        return value.replace("_", "-").lower()
