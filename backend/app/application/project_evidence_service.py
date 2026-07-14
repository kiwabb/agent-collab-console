from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_typescript as tree_sitter_ts
from tree_sitter import Language, Node, Parser

from app.adapters.project_source_reader import RepositoryBoundary, RepositoryBoundaryError
from app.domain.models import Project
from app.domain.project_evidence import (
    Confidence,
    EvidenceKind,
    EvidenceLocation,
    PackageSurface,
    ProjectSurfaceManifest,
    PrototypeCandidate,
    SupportLevel,
    SurfaceKind,
    source_line_count,
)


class ProjectEvidenceError(ValueError):
    """Raised when deterministic project evidence cannot be produced."""


@dataclass(frozen=True)
class _PackageContext:
    surface: PackageSurface
    root: Path
    manifest: dict[str, object]


@dataclass
class _RouteRecord:
    route_pattern: str
    component_ref: str | None
    component_path: str | None
    source_path: str
    start_line: int
    end_line: int
    is_index: bool = False
    is_redirect: bool = False
    is_wildcard: bool = False
    layout_paths: list[str] = field(default_factory=list)
    state_name: str = "default"


@dataclass
class _CandidateGroup:
    records: list[_RouteRecord] = field(default_factory=list)


class ProjectEvidenceService:
    """Collect bounded, deterministic evidence for project UI surfaces."""

    def scan_project(self, project: Project) -> ProjectSurfaceManifest:
        try:
            boundary = RepositoryBoundary.from_repo_path(project.repo_path)
            files = boundary.iter_files()
            packages = self._discover_packages(boundary, files)
            candidates: list[PrototypeCandidate] = []
            diagnostics: list[str] = []
            for package in packages:
                diagnostics.extend(
                    f"{package.surface.package_root}: {message}"
                    for message in package.surface.diagnostics
                )
                if package.surface.support == "unsupported":
                    continue
                if package.surface.surface_kind == "web":
                    if "react-router" in package.surface.framework_signals:
                        candidates.extend(self._react_router_candidates(boundary, package))
                    elif "vue-router" in package.surface.framework_signals:
                        candidates.extend(self._vue_router_candidates(boundary, package))
                    elif any(
                        signal.startswith("next-") for signal in package.surface.framework_signals
                    ):
                        candidates.extend(self._next_candidates(boundary, package))
                    else:
                        candidates.extend(self._fallback_candidates(boundary, package))
        except RepositoryBoundaryError as exc:
            raise ProjectEvidenceError(str(exc)) from exc
        except (OSError, UnicodeError) as exc:
            raise ProjectEvidenceError("repository evidence scan failed") from exc

        candidates.sort(
            key=lambda item: (item.package_root, item.route_patterns, item.candidate_id)
        )
        fingerprint = self._fingerprint(boundary, packages, candidates)
        return ProjectSurfaceManifest(
            repository_root=boundary.root.as_posix(),
            packages=tuple(package.surface for package in packages),
            candidates=tuple(candidates),
            diagnostics=tuple(sorted(set(diagnostics))),
            repository_fingerprint=fingerprint,
        )

    def _discover_packages(
        self, boundary: RepositoryBoundary, files: list[Path]
    ) -> list[_PackageContext]:
        contexts: list[_PackageContext] = []
        for manifest_path in files:
            if manifest_path.name != "package.json":
                continue
            relative = boundary.relative_path(manifest_path)
            if len(Path(relative).parts) > 5:
                continue
            raw = boundary.read_text(manifest_path)
            try:
                manifest = json.loads(raw)
            except json.JSONDecodeError:
                contexts.append(
                    _PackageContext(
                        surface=PackageSurface(
                            package_root=Path(relative).parent.as_posix(),
                            manifest_path=relative,
                            name=Path(relative).parent.name,
                            support="partial",
                            diagnostics=("package.json is not valid JSON",),
                        ),
                        root=manifest_path.parent,
                        manifest={},
                    )
                )
                continue
            if not isinstance(manifest, dict):
                continue
            surface = self._package_surface(boundary, manifest_path, manifest, files)
            contexts.append(
                _PackageContext(surface=surface, root=manifest_path.parent, manifest=manifest)
            )
        return sorted(contexts, key=lambda item: item.surface.package_root)

    def _package_surface(
        self,
        boundary: RepositoryBoundary,
        manifest_path: Path,
        manifest: dict[str, object],
        files: list[Path],
    ) -> PackageSurface:
        relative = boundary.relative_path(manifest_path)
        package_root = Path(relative).parent.as_posix()
        if package_root == ".":
            package_root = ""
        name = str(manifest.get("name") or Path(package_root).name or boundary.root.name)
        dependencies = self._package_names(manifest, "dependencies")
        dev_dependencies = self._package_names(manifest, "devDependencies")
        all_dependencies = dependencies | dev_dependencies
        scripts = manifest.get("scripts")
        script_text = json.dumps(scripts, ensure_ascii=False) if isinstance(scripts, dict) else ""
        package_relative_files = {
            path.relative_to(manifest_path.parent).as_posix()
            for path in files
            if path.is_relative_to(manifest_path.parent)
        }
        is_extension = (
            "web-ext" in all_dependencies
            or "webextension-polyfill" in all_dependencies
            or "extension" in name.lower()
            or "src/manifest.ts" in package_relative_files
            or "web-ext" in script_text
        )
        is_next = "next" in all_dependencies
        is_react_router = "react-router-dom" in all_dependencies
        is_react = "react" in all_dependencies
        is_vue = "vue" in all_dependencies
        is_vue_router = "vue-router" in all_dependencies
        signals: set[str] = set()
        if is_next:
            signals.add(
                "next-app-router" if self._has_route_dir(package_relative_files, "app") else "next"
            )
        if "vite" in all_dependencies:
            signals.add("vite")
        if is_react:
            signals.add("react")
        if is_react_router:
            signals.add("react-router")
        if is_vue:
            signals.add("vue")
        if is_vue_router:
            signals.add("vue-router")
        if is_extension:
            signals.add("browser-extension")
        surface_kind: SurfaceKind = (
            "browser-extension"
            if is_extension
            else ("web" if is_react or is_vue or is_next else "unknown")
        )
        diagnostics: tuple[str, ...]
        support: SupportLevel
        if surface_kind == "browser-extension":
            support = "unsupported"
            diagnostics = ("browser extension surface is detected but not supported in MVP",)
        elif is_react_router or is_vue_router or is_next:
            support = "supported"
            diagnostics = ()
        elif is_react:
            support = "partial"
            diagnostics = (
                "React package has no supported route declaration; fallback discovery is low confidence",
            )
        else:
            support = "unsupported"
            diagnostics = ("no supported web framework signal was found",)
        entry_candidates = tuple(
            candidate
            for candidate in (
                self._relative_if_exists(boundary, manifest_path.parent / "src/App.tsx"),
                self._relative_if_exists(boundary, manifest_path.parent / "src/app.tsx"),
                self._relative_if_exists(boundary, manifest_path.parent / "src/main.tsx"),
                self._relative_if_exists(boundary, manifest_path.parent / "src/router.ts"),
                self._relative_if_exists(boundary, manifest_path.parent / "src/router.js"),
                self._relative_if_exists(boundary, manifest_path.parent / "src/App.vue"),
                self._relative_if_exists(boundary, manifest_path.parent / "src/main.ts"),
                self._relative_if_exists(boundary, manifest_path.parent / "app"),
                self._relative_if_exists(boundary, manifest_path.parent / "pages"),
            )
            if candidate is not None
        )
        style_candidates = tuple(
            sorted(
                boundary.relative_path(manifest_path.parent / path)
                for path in package_relative_files
                if path.endswith((".css", ".scss", ".less"))
                and Path(path).name
                in {"index.css", "App.css", "globals.css", "main.css", "styles.css"}
            )
        )
        return PackageSurface(
            package_root=package_root,
            manifest_path=relative,
            name=name,
            framework_signals=tuple(sorted(signals)),
            surface_kind=surface_kind,
            support=support,
            entry_candidates=entry_candidates,
            style_candidates=style_candidates,
            diagnostics=diagnostics,
        )

    def _react_router_candidates(
        self, boundary: RepositoryBoundary, package: _PackageContext
    ) -> list[PrototypeCandidate]:
        entry = self._first_existing_entry(boundary, package)
        if entry is None:
            return [
                self._diagnostic_candidate(
                    package.surface,
                    package.surface.manifest_path,
                    "React Router package has no readable route entry",
                )
            ]
        source = boundary.read_text(entry)
        router_aliases = self._react_router_aliases(source)
        parser = Parser(Language(tree_sitter_ts.language_tsx()))
        tree = parser.parse(source.encode("utf-8"))
        if tree.root_node.has_error:
            return [
                self._diagnostic_candidate(
                    package.surface,
                    boundary.relative_path(entry),
                    "React Router entry contains syntax errors; route candidates are partial",
                )
            ]
        import_map = self._collect_imports(
            tree.root_node, source.encode("utf-8"), package.root, entry.parent, boundary
        )
        groups: list[_CandidateGroup] = []
        diagnostic_candidates: list[PrototypeCandidate] = []
        routes_nodes = [
            node
            for node in self._walk_nodes(tree.root_node)
            if router_aliases.get(self._tag_name(node, source.encode("utf-8")) or "") == "Routes"
        ]
        for routes_node in routes_nodes:
            self._walk_route_children(
                routes_node,
                parent_path="",
                layout_paths=[],
                active_group=None,
                groups=groups,
                source=source.encode("utf-8"),
                entry=entry,
                import_map=import_map,
                package=package,
                boundary=boundary,
                router_aliases=router_aliases,
                diagnostic_candidates=diagnostic_candidates,
            )
        candidates = [self._candidate_from_group(group, package, boundary) for group in groups]
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        for candidate in diagnostic_candidates:
            by_id.setdefault(candidate.candidate_id, candidate)
        return list(by_id.values())

    def _walk_route_children(
        self,
        parent: Node,
        *,
        parent_path: str,
        layout_paths: list[str],
        active_group: _CandidateGroup | None,
        groups: list[_CandidateGroup],
        source: bytes,
        entry: Path,
        import_map: dict[str, Path],
        package: _PackageContext,
        boundary: RepositoryBoundary,
        router_aliases: dict[str, str],
        diagnostic_candidates: list[PrototypeCandidate],
    ) -> None:
        for child in parent.named_children:
            if router_aliases.get(self._tag_name(child, source) or "") != "Route":
                continue
            attrs = self._jsx_attributes(child, source)
            raw_path = attrs.get("path")
            path_value = (
                self._static_string_value(raw_path, source) if isinstance(raw_path, Node) else None
            )
            if isinstance(raw_path, Node) and path_value is None:
                diagnostic_candidates.append(
                    self._diagnostic_candidate(
                        package.surface,
                        boundary.relative_path(entry),
                        f"React Router path at line {child.start_point.row + 1} is not statically evaluable",
                    )
                )
                continue
            is_index = "index" in attrs
            route_path = self._join_route(parent_path, path_value, is_index)
            element_tags = self._element_tags(attrs.get("element"), source)
            component_ref = self._last_component(element_tags)
            component_path = self._resolve_component_path(component_ref, import_map)
            is_redirect = any(router_aliases.get(tag) == "Navigate" for tag in element_tags)
            is_wildcard = path_value == "*"
            meaningful = self._is_meaningful_component(component_ref, component_path, boundary)
            record = _RouteRecord(
                route_pattern=route_path,
                component_ref=component_ref,
                component_path=boundary.relative_path(component_path) if component_path else None,
                source_path=boundary.relative_path(entry),
                start_line=child.start_point.row + 1,
                end_line=child.end_point.row + 1,
                is_index=is_index,
                is_redirect=is_redirect,
                is_wildcard=is_wildcard,
                layout_paths=list(layout_paths),
                state_name=self._state_name(path_value, is_index),
            )
            group = active_group
            if not is_redirect and not is_wildcard and meaningful and group is None:
                group = _CandidateGroup()
                groups.append(group)
            if (
                group is not None
                and not is_redirect
                and not is_wildcard
                and (meaningful or component_ref)
            ):
                group.records.append(record)
            next_layouts = list(layout_paths)
            if component_path and (not meaningful or not path_value):
                next_layouts.append(boundary.relative_path(component_path))
            self._walk_route_children(
                child,
                parent_path=route_path,
                layout_paths=next_layouts,
                active_group=group,
                groups=groups,
                source=source,
                entry=entry,
                import_map=import_map,
                package=package,
                boundary=boundary,
                router_aliases=router_aliases,
                diagnostic_candidates=diagnostic_candidates,
            )

    def _candidate_from_group(
        self,
        group: _CandidateGroup,
        package: _PackageContext,
        boundary: RepositoryBoundary,
        *,
        framework_hint: str = "react-router",
        evidence_kind: EvidenceKind = "react-router-route",
    ) -> PrototypeCandidate:
        records = sorted(group.records, key=lambda item: (item.route_pattern, item.start_line))
        primary = records[0]
        route_patterns = tuple(dict.fromkeys(item.route_pattern or "/" for item in records))
        source_paths = tuple(
            dict.fromkeys(item.component_path for item in records if item.component_path)
        )
        layout_paths = tuple(
            dict.fromkeys(
                path for item in records for path in item.layout_paths if path not in source_paths
            )
        )
        confidence: Confidence = "high" if all(item.component_ref for item in records) else "medium"
        route_evidence = tuple(
            EvidenceLocation(
                path=item.source_path,
                start_line=item.start_line,
                end_line=item.end_line,
                kind=evidence_kind,
                detail=f"{item.component_ref or 'layout'} -> {item.route_pattern or '/'}",
                content=self._line_excerpt(
                    boundary.read_text(boundary.root / item.source_path),
                    item.start_line,
                    item.end_line,
                ),
                confidence=confidence,
            )
            for item in records
        )
        content_evidence = tuple(
            file_evidence
            for path in dict.fromkeys(
                (*source_paths, *layout_paths, *package.surface.style_candidates)
            )
            if (
                file_evidence := self._file_evidence(
                    boundary,
                    path,
                    (
                        "layout"
                        if path in layout_paths
                        else (
                            "style" if path in package.surface.style_candidates else "page-source"
                        )
                    ),
                    confidence,
                )
            )
            is not None
        )
        evidence = (*route_evidence, *content_evidence)
        candidate_key = "|".join(
            (package.surface.package_root, primary.component_ref or "route", route_patterns[0])
        )
        candidate_id = (
            framework_hint + "--" + hashlib.sha256(candidate_key.encode()).hexdigest()[:20]
        )
        states = tuple(dict.fromkeys(item.state_name for item in records)) or ("default",)
        content_hashes = []
        for path in (*source_paths, *layout_paths, *package.surface.style_candidates):
            content_hashes.append(
                f"{path}|{hashlib.sha256(boundary.read_text(boundary.root / path).encode()).hexdigest()}"
            )
        hash_input = "\n".join(
            [
                *(
                    f"{item.route_pattern}|{item.component_ref}|{item.source_path}|{item.start_line}|{item.end_line}"
                    for item in records
                ),
                *content_hashes,
            ]
        )
        source_hash = "sha256:" + hashlib.sha256(hash_input.encode()).hexdigest()
        return PrototypeCandidate(
            candidate_id=candidate_id,
            title=self._humanize(primary.component_ref or primary.route_pattern or "Page"),
            route_patterns=route_patterns,
            surface_kind=package.surface.surface_kind,
            package_root=package.surface.package_root,
            framework_hint=framework_hint,
            primary_source_path=primary.component_path,
            source_paths=source_paths,
            layout_paths=layout_paths,
            evidence=evidence,
            confidence=confidence,
            source_hash=source_hash,
            states=states,
        )

    def _vue_router_candidates(
        self, boundary: RepositoryBoundary, package: _PackageContext
    ) -> list[PrototypeCandidate]:
        entry = next(
            (
                package.root / relative
                for relative in ("src/router.ts", "src/router.js")
                if (package.root / relative).is_file()
            ),
            None,
        )
        if entry is None:
            return [
                self._diagnostic_candidate(
                    package.surface,
                    package.surface.manifest_path,
                    "Vue Router package has no readable src/router.ts or src/router.js entry",
                )
            ]
        source = boundary.read_text(entry)
        source_bytes = source.encode("utf-8")
        parser = Parser(Language(tree_sitter_ts.language_typescript()))
        tree = parser.parse(source_bytes)
        if tree.root_node.has_error:
            return [
                self._diagnostic_candidate(
                    package.surface,
                    boundary.relative_path(entry),
                    "Vue Router entry contains syntax errors; route candidates are partial",
                )
            ]
        import_map = self._collect_imports(
            tree.root_node, source_bytes, package.root, entry.parent, boundary
        )
        create_router_aliases = self._vue_create_router_aliases(source)
        route_arrays: list[Node] = []
        for node in self._walk_nodes(tree.root_node):
            if node.type != "call_expression":
                continue
            function = node.child_by_field_name("function")
            if function is None:
                continue
            function_name = source_bytes[function.start_byte : function.end_byte].decode()
            if function_name not in create_router_aliases:
                continue
            arguments = node.child_by_field_name("arguments")
            config = (
                next((child for child in arguments.named_children if child.type == "object"), None)
                if arguments is not None
                else None
            )
            routes = self._object_property(config, "routes", source_bytes) if config else None
            if routes is not None and routes.type == "array":
                route_arrays.append(routes)

        if not route_arrays:
            return [
                self._diagnostic_candidate(
                    package.surface,
                    boundary.relative_path(entry),
                    "Vue Router routes must be a static array inside createRouter",
                )
            ]

        groups: list[_CandidateGroup] = []
        diagnostics: list[PrototypeCandidate] = []
        app_layout = package.root / "src/App.vue"
        base_layouts = [boundary.relative_path(app_layout)] if app_layout.is_file() else []
        for routes in route_arrays:
            self._walk_vue_route_array(
                routes,
                parent_path="",
                layout_paths=base_layouts,
                groups=groups,
                diagnostics=diagnostics,
                source=source_bytes,
                entry=entry,
                import_map=import_map,
                package=package,
                boundary=boundary,
            )
        candidates = [
            self._candidate_from_group(
                group,
                package,
                boundary,
                framework_hint="vue-router",
                evidence_kind="vue-router-route",
            )
            for group in groups
        ]
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        for candidate in diagnostics:
            by_id.setdefault(candidate.candidate_id, candidate)
        return list(by_id.values())

    def _walk_vue_route_array(
        self,
        routes: Node,
        *,
        parent_path: str,
        layout_paths: list[str],
        groups: list[_CandidateGroup],
        diagnostics: list[PrototypeCandidate],
        source: bytes,
        entry: Path,
        import_map: dict[str, Path],
        package: _PackageContext,
        boundary: RepositoryBoundary,
    ) -> None:
        for route in routes.named_children:
            if route.type != "object":
                diagnostics.append(
                    self._diagnostic_candidate(
                        package.surface,
                        boundary.relative_path(entry),
                        f"Vue Router record at line {route.start_point.row + 1} is not a static object",
                    )
                )
                continue
            raw_path = self._object_property(route, "path", source)
            path_value = self._static_string_value(raw_path, source) if raw_path else None
            if raw_path is None or path_value is None:
                diagnostics.append(
                    self._diagnostic_candidate(
                        package.surface,
                        boundary.relative_path(entry),
                        f"Vue Router path at line {route.start_point.row + 1} is not statically evaluable",
                    )
                )
                continue
            route_path = self._join_route(parent_path, path_value, False)
            redirect = self._object_property(route, "redirect", source)
            component = self._object_property(route, "component", source)
            children = self._object_property(route, "children", source)
            component_ref, component_path = self._vue_component(
                component, source, import_map, package, entry, boundary
            )
            is_wildcard = path_value == "*" or "pathMatch" in path_value
            if component is not None and component_path is None and redirect is None:
                diagnostics.append(
                    self._diagnostic_candidate(
                        package.surface,
                        boundary.relative_path(entry),
                        f"Vue Router component at line {route.start_point.row + 1} cannot be resolved",
                    )
                )
            if redirect is None and not is_wildcard and component_path is not None:
                groups.append(
                    _CandidateGroup(
                        records=[
                            _RouteRecord(
                                route_pattern=route_path,
                                component_ref=component_ref,
                                component_path=boundary.relative_path(component_path),
                                source_path=boundary.relative_path(entry),
                                start_line=route.start_point.row + 1,
                                end_line=route.end_point.row + 1,
                                layout_paths=list(layout_paths),
                                state_name=self._state_name(path_value, False),
                            )
                        ]
                    )
                )
            next_layouts = list(layout_paths)
            if component_path is not None and children is not None:
                next_layouts.append(boundary.relative_path(component_path))
            if children is not None:
                if children.type == "array":
                    self._walk_vue_route_array(
                        children,
                        parent_path=route_path,
                        layout_paths=next_layouts,
                        groups=groups,
                        diagnostics=diagnostics,
                        source=source,
                        entry=entry,
                        import_map=import_map,
                        package=package,
                        boundary=boundary,
                    )
                else:
                    diagnostics.append(
                        self._diagnostic_candidate(
                            package.surface,
                            boundary.relative_path(entry),
                            f"Vue Router children at line {route.start_point.row + 1} must be a static array",
                        )
                    )

    def _vue_component(
        self,
        component: Node | None,
        source: bytes,
        import_map: dict[str, Path],
        package: _PackageContext,
        entry: Path,
        boundary: RepositoryBoundary,
    ) -> tuple[str | None, Path | None]:
        if component is None:
            return None, None
        if component.type == "identifier":
            name = source[component.start_byte : component.end_byte].decode()
            return name, import_map.get(name)
        dynamic_import = next(
            (
                node
                for node in self._walk_nodes(component)
                if node.type == "call_expression"
                and source[node.start_byte : node.end_byte].startswith(b"import(")
            ),
            None,
        )
        if dynamic_import is None:
            return None, None
        arguments = dynamic_import.child_by_field_name("arguments")
        string_node = (
            next((child for child in arguments.named_children if child.type == "string"), None)
            if arguments is not None
            else None
        )
        if string_node is None:
            return None, None
        spec = self._string_value(string_node, source)
        resolved = self._resolve_import(spec, package.root, entry.parent, boundary)
        return Path(spec).stem, resolved

    def _object_property(self, node: Node, name: str, source: bytes) -> Node | None:
        for child in node.named_children:
            if child.type != "pair":
                continue
            key = child.child_by_field_name("key")
            if key is None or source[key.start_byte : key.end_byte].decode().strip("'\"") != name:
                continue
            return child.child_by_field_name("value")
        return None

    def _vue_create_router_aliases(self, source: str) -> set[str]:
        aliases = {"createRouter"}
        for match in re.finditer(
            r"import\s*\{(?P<imports>[^}]*)\}\s*from\s*['\"]vue-router['\"]",
            source,
            re.DOTALL,
        ):
            for specifier in match.group("imports").split(","):
                parts = [part.strip() for part in re.split(r"\s+as\s+", specifier.strip())]
                if parts and parts[0] == "createRouter":
                    aliases.add(parts[-1])
        return aliases

    def _next_candidates(
        self, boundary: RepositoryBoundary, package: _PackageContext
    ) -> list[PrototypeCandidate]:
        prefix = (
            package.root / "app"
            if "next-app-router" in package.surface.framework_signals
            else package.root / "pages"
        )
        candidates: list[PrototypeCandidate] = []
        for path in boundary.iter_files():
            if not path.is_relative_to(prefix) or path.suffix not in {".tsx", ".jsx"}:
                continue
            if path.name not in {"page.tsx", "page.jsx"} and prefix.name == "app":
                continue
            relative = path.relative_to(package.root).as_posix()
            if prefix.name == "pages" and path.stem.startswith("_"):
                continue
            route = self._file_route(relative, prefix.name)
            if route is None:
                continue
            source = boundary.read_text(path)
            line_count = source_line_count(source)
            style_evidence = tuple(
                file_evidence
                for style_path in package.surface.style_candidates
                if (file_evidence := self._file_evidence(boundary, style_path, "style")) is not None
            )
            evidence = (
                EvidenceLocation(
                    relative,
                    1,
                    line_count,
                    "file-route",
                    route,
                    self._bounded_content(source),
                    confidence="high",
                ),
                *style_evidence,
            )
            key = f"{package.surface.package_root}|next|{route}"
            content_hash = hashlib.sha256(source.encode()).hexdigest()
            style_hashes = [
                hashlib.sha256(boundary.read_text(boundary.root / style_path).encode()).hexdigest()
                for style_path in package.surface.style_candidates
            ]
            candidates.append(
                PrototypeCandidate(
                    candidate_id="next--" + hashlib.sha256(key.encode()).hexdigest()[:20],
                    title=self._humanize(route.strip("/").replace("/", " ") or "Home"),
                    route_patterns=(route,),
                    surface_kind=package.surface.surface_kind,
                    package_root=package.surface.package_root,
                    framework_hint="next-app-router"
                    if prefix.name == "app"
                    else "next-pages-router",
                    primary_source_path=relative,
                    source_paths=(relative,),
                    layout_paths=(),
                    evidence=evidence,
                    confidence="high",
                    source_hash="sha256:"
                    + hashlib.sha256(
                        "|".join((relative, content_hash, *style_hashes)).encode()
                    ).hexdigest(),
                )
            )
        return candidates

    def _fallback_candidates(
        self, boundary: RepositoryBoundary, package: _PackageContext
    ) -> list[PrototypeCandidate]:
        candidates: list[PrototypeCandidate] = []
        for path in boundary.iter_files():
            if not path.is_relative_to(package.root) or path.suffix not in {".tsx", ".jsx"}:
                continue
            relative = path.relative_to(package.root).as_posix()
            if not (relative.startswith("src/pages/") or relative.startswith("src/routes/")):
                continue
            route = "/" + path.stem.replace("index", "").strip("/")
            source = boundary.read_text(path)
            candidates.append(
                PrototypeCandidate(
                    candidate_id="fallback--"
                    + hashlib.sha256(
                        f"{package.surface.package_root}|{relative}".encode()
                    ).hexdigest()[:20],
                    title=self._humanize(path.stem),
                    route_patterns=(route or "/",),
                    surface_kind=package.surface.surface_kind,
                    package_root=package.surface.package_root,
                    framework_hint="react-page-directory",
                    primary_source_path=relative,
                    source_paths=(relative,),
                    layout_paths=(),
                    evidence=(
                        EvidenceLocation(
                            relative,
                            1,
                            source.count("\n") + 1,
                            "page-directory",
                            "directory fallback",
                            self._bounded_content(source),
                            confidence="low",
                            diagnostic=(
                                "route declaration was not found; directory fallback is low confidence"
                            ),
                        ),
                    ),
                    confidence="low",
                    source_hash="sha256:"
                    + hashlib.sha256(f"{relative}|{source}".encode()).hexdigest(),
                    diagnostics=(
                        "route declaration was not found; directory fallback is low confidence",
                    ),
                )
            )
        return candidates

    def _diagnostic_candidate(
        self, package: PackageSurface, source_path: str, message: str
    ) -> PrototypeCandidate:
        key = f"{package.package_root}|partial|{source_path}"
        return PrototypeCandidate(
            candidate_id="partial--" + hashlib.sha256(key.encode()).hexdigest()[:20],
            title="Route analysis needs review",
            route_patterns=(),
            surface_kind=package.surface_kind,
            package_root=package.package_root,
            framework_hint="react-router",
            primary_source_path=source_path,
            source_paths=(source_path,),
            layout_paths=(),
            evidence=(
                EvidenceLocation(
                    source_path,
                    1,
                    1,
                    "parser",
                    message,
                    confidence="low",
                    diagnostic=message,
                ),
            ),
            confidence="low",
            source_hash="sha256:" + hashlib.sha256(key.encode()).hexdigest(),
            diagnostics=(message,),
            action="unsupported",
        )

    def _collect_imports(
        self,
        root: Node,
        source: bytes,
        package_root: Path,
        source_parent: Path,
        boundary: RepositoryBoundary,
    ) -> dict[str, Path]:
        imports: dict[str, Path] = {}
        for node in self._walk_nodes(root):
            if node.type == "import_statement":
                strings = [child for child in node.named_children if child.type == "string"]
                if not strings:
                    continue
                spec = self._string_value(strings[-1], source)
                clause = next(
                    (child for child in node.named_children if child.type == "import_clause"), None
                )
                if clause is None:
                    continue
                locals_found = self._import_locals(clause, source)
                resolved = self._resolve_import(spec, package_root, source_parent, boundary)
                if resolved:
                    imports.update({name: resolved for name in locals_found})
            elif node.type == "variable_declarator":
                name = node.child_by_field_name("name")
                value = node.child_by_field_name("value")
                if name is None or value is None or value.type != "call_expression":
                    continue
                dynamic = next(
                    (
                        child
                        for child in self._walk_nodes(value)
                        if child.type == "call_expression"
                        and source[child.start_byte : child.end_byte].startswith(b"import(")
                    ),
                    None,
                )
                if dynamic is None:
                    continue
                string_node = next(
                    (
                        child
                        for child in dynamic.named_children
                        if child.type == "arguments"
                        for child in child.named_children
                        if child.type == "string"
                    ),
                    None,
                )
                if string_node is None:
                    continue
                resolved = self._resolve_import(
                    self._string_value(string_node, source), package_root, source_parent, boundary
                )
                if resolved:
                    imports[source[name.start_byte : name.end_byte].decode()] = resolved
        return imports

    def _import_locals(self, clause: Node, source: bytes) -> list[str]:
        locals_found: list[str] = []
        for node in clause.named_children:
            if node.type == "identifier":
                locals_found.append(source[node.start_byte : node.end_byte].decode())
            elif node.type == "named_imports":
                for specifier in node.named_children:
                    if specifier.type != "import_specifier":
                        continue
                    identifiers = [
                        child
                        for child in specifier.named_children
                        if child.type in {"identifier", "property_identifier"}
                    ]
                    if identifiers:
                        locals_found.append(
                            source[identifiers[-1].start_byte : identifiers[-1].end_byte].decode()
                        )
        return locals_found

    def _resolve_import(
        self,
        spec: str,
        package_root: Path,
        source_parent: Path,
        boundary: RepositoryBoundary,
    ) -> Path | None:
        if spec.startswith("@/"):
            base = package_root / "src" / spec[2:]
        elif spec.startswith("."):
            base = source_parent / spec
        else:
            return None
        return boundary.resolve_source(base)

    def _resolve_component_path(
        self, component_ref: str | None, import_map: dict[str, Path]
    ) -> Path | None:
        return import_map.get(component_ref) if component_ref else None

    def _first_existing_entry(
        self, boundary: RepositoryBoundary, package: _PackageContext
    ) -> Path | None:
        for relative in package.surface.entry_candidates:
            path = boundary.root / relative
            if path.is_file() and path.suffix in {".tsx", ".jsx", ".ts", ".js"}:
                return path
        return None

    def _jsx_attributes(self, node: Node, source: bytes) -> dict[str, object]:
        opening = node.child_by_field_name("open_tag") or node
        attributes: dict[str, object] = {}
        for attr in opening.named_children:
            if attr.type != "jsx_attribute" or not attr.named_children:
                continue
            name = source[
                attr.named_children[0].start_byte : attr.named_children[0].end_byte
            ].decode()
            if len(attr.named_children) == 1:
                attributes[name] = True
            else:
                attributes[name] = attr.named_children[1]
        return attributes

    def _element_tags(self, value: object, source: bytes) -> list[str]:
        if not isinstance(value, Node):
            return []
        return [
            tag
            for node in self._walk_nodes(value)
            if (tag := self._tag_name(node, source)) is not None and tag[0].isupper()
        ]

    def _string_value(self, node: Node, source: bytes) -> str:
        if node.type == "string":
            fragment = next(
                (child for child in node.named_children if child.type == "string_fragment"), None
            )
            if fragment is not None:
                return source[fragment.start_byte : fragment.end_byte].decode()
        raw = source[node.start_byte : node.end_byte].decode().strip()
        return raw[1:-1] if len(raw) >= 2 and raw[0] in {"'", '"', "`"} else raw

    def _static_string_value(self, node: Node, source: bytes) -> str | None:
        if node.type == "string":
            return self._string_value(node, source)
        raw = source[node.start_byte : node.end_byte].decode().strip()
        if raw.startswith("{") and raw.endswith("}"):
            expression = raw[1:-1].strip()
            if (
                len(expression) >= 2
                and expression[0] == expression[-1]
                and expression[0] in {"'", '"'}
            ):
                return expression[1:-1]
            if expression.startswith("`") and expression.endswith("`") and "${" not in expression:
                return expression[1:-1]
        return None

    def _react_router_aliases(self, source: str) -> dict[str, str]:
        aliases: dict[str, str] = {"Routes": "Routes", "Route": "Route", "Navigate": "Navigate"}
        for match in re.finditer(
            r"import\s*\{(?P<imports>[^}]*)\}\s*from\s*['\"]react-router-dom['\"]",
            source,
            re.DOTALL,
        ):
            for specifier in match.group("imports").split(","):
                parts = [part.strip() for part in re.split(r"\s+as\s+", specifier.strip())]
                if not parts or parts[0] not in {"Routes", "Route", "Navigate"}:
                    continue
                aliases[parts[-1]] = parts[0]
        return aliases

    def _last_component(self, tags: list[str]) -> str | None:
        return tags[-1] if tags else None

    def _tag_name(self, node: Node, source: bytes) -> str | None:
        if node.type not in {"jsx_element", "jsx_self_closing_element"}:
            return None
        opening = node.child_by_field_name("open_tag") or node
        for child in opening.named_children:
            if child.type in {"identifier", "nested_identifier", "member_expression"}:
                return source[child.start_byte : child.end_byte].decode()
        return None

    def _walk_nodes(self, node: Node) -> Iterable[Node]:
        yield node
        for child in node.children:
            yield from self._walk_nodes(child)

    def _is_meaningful_component(
        self, component_ref: str | None, component_path: Path | None, boundary: RepositoryBoundary
    ) -> bool:
        if component_ref in {None, "Index", "SettingPage", "MainLayout", "OnboardingGuard"}:
            return False
        if component_path is None:
            return True
        content = boundary.read_text(component_path)
        if "<Outlet" not in content:
            return True
        meaningful_tags = re.findall(r"<([A-Z][A-Za-z0-9_]*)\b", content)
        return any(tag not in {"Outlet", component_ref} for tag in meaningful_tags)

    def _join_route(self, parent: str, child: str | None, is_index: bool) -> str:
        if is_index or not child:
            return parent or "/"
        if child.startswith("/"):
            return child or "/"
        return "/" + "/".join(part for part in (parent.strip("/"), child.strip("/")) if part)

    def _state_name(self, path: str | None, is_index: bool) -> str:
        if is_index or not path:
            return "default"
        if path == "new":
            return "new"
        if path.startswith(":"):
            return "edit"
        return path.strip("/").replace("/", "-") or "default"

    def _file_route(self, relative: str, prefix: str) -> str | None:
        stem = relative.removeprefix(f"{prefix}/").rsplit(".", 1)[0]
        if (
            prefix == "app"
            and not relative.endswith("/page.tsx")
            and not relative.endswith("/page.jsx")
        ):
            return None
        segments = [part for part in stem.split("/") if part not in {"index", "page"}]
        return "/" + "/".join(self._route_segment(part) for part in segments) if segments else "/"

    def _route_segment(self, segment: str) -> str:
        if segment.startswith("[[...") and segment[-2:] == "]]":
            return f":{segment[5:-2]}*"
        if segment.startswith("[...") and segment.endswith("]"):
            return f":{segment[4:-1]}*"
        if segment.startswith("[") and segment.endswith("]"):
            return f":{segment[1:-1]}"
        if segment.startswith("(") and segment.endswith(")"):
            return ""
        return segment

    def _has_route_dir(self, paths: set[str], name: str) -> bool:
        return any(path == name or path.startswith(f"{name}/") for path in paths)

    def _relative_if_exists(self, boundary: RepositoryBoundary, path: Path) -> str | None:
        if path.exists():
            return boundary.relative_path(path)
        return None

    def _package_names(self, manifest: dict[str, object], key: str) -> set[str]:
        value = manifest.get(key)
        return set(value) if isinstance(value, dict) else set()

    def _fingerprint(
        self,
        boundary: RepositoryBoundary,
        packages: list[_PackageContext],
        candidates: list[PrototypeCandidate],
    ) -> str:
        value = "\n".join(
            [
                boundary.root.as_posix(),
                *(f"{p.surface.manifest_path}|{p.surface.name}" for p in packages),
                *(f"{c.candidate_id}|{c.source_hash}" for c in candidates),
            ]
        )
        return "sha256:" + hashlib.sha256(value.encode()).hexdigest()

    def _file_evidence(
        self,
        boundary: RepositoryBoundary,
        relative_path: str,
        kind: EvidenceKind,
        confidence: Confidence = "high",
    ) -> EvidenceLocation | None:
        source = boundary.read_text(boundary.root / relative_path)
        if not source.strip():
            return None
        return EvidenceLocation(
            path=relative_path,
            start_line=1,
            end_line=source_line_count(source),
            kind=kind,
            detail="bounded source evidence",
            content=self._bounded_content(source),
            confidence=confidence,
        )

    def _bounded_content(self, source: str, *, max_chars: int = 12_000) -> str:
        return source[:max_chars]

    def _line_excerpt(self, source: str, start_line: int, end_line: int) -> str:
        lines = source.splitlines()
        excerpt = "\n".join(lines[max(0, start_line - 1) : min(len(lines), end_line)])
        return self._bounded_content(excerpt, max_chars=4_000)

    def _humanize(self, value: str) -> str:
        text = value.strip("/") or "Home"
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        text = text.replace("-", " ").replace("_", " ").replace(":", " ")
        return " ".join(part.capitalize() for part in text.split())
