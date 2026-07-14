from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adapters.project_source_reader import RepositoryBoundary, RepositoryBoundaryError
from app.application.project_evidence_service import ProjectEvidenceError, ProjectEvidenceService
from app.domain.models import Project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _react_fixture(root: Path) -> None:
    package = root / "VideoMemo_frontend"
    _write(
        package / "package.json",
        json.dumps(
            {
                "name": "video-memo",
                "dependencies": {
                    "react": "19",
                    "react-router-dom": "7",
                    "vite": "6",
                },
            }
        ),
    )
    routes = [
        ("onboarding", "Onboarding"),
        ("articles", "Articles"),
        ("batch-import", "BatchImport"),
        ("collections", "Collections"),
        ("collections/:id", "CollectionDetail"),
        ("guide", "Guide"),
        ("knowledge", "Knowledge"),
        ("settings/about", "AboutPage"),
        ("settings/access-password", "AccessPassword"),
        ("settings/feishu", "FeishuPage"),
        ("settings/local-downloader", "LocalDownloaderPage"),
        ("settings/monitor", "Monitor"),
        ("settings/transcriber", "TranscriberPage"),
        ("subscriptions", "Subscriptions"),
        ("tasks", "TaskList"),
        ("trends", "Trends"),
    ]
    lazy_declarations = [
        f"const {component} = lazy(() => import('./pages/{component}'))" for _, component in routes
    ]
    route_lines = [
        f'<Route path="{path}" element={{<{component} />}} />' for path, component in routes
    ]
    _write(
        package / "src/App.tsx",
        "\n".join(
            [
                "import { lazy } from 'react'",
                "import { Navigate, Route, Routes } from 'react-router-dom'",
                "const Layout = lazy(() => import('./layouts/Layout'))",
                "const Settings = lazy(() => import('./layouts/Settings'))",
                "const HomePage = lazy(() => import('./pages/HomePage'))",
                "const Model = lazy(() => import('./pages/Model'))",
                "const ProviderForm = lazy(() => import('./pages/ProviderForm'))",
                "const Downloader = lazy(() => import('./pages/Downloader'))",
                "const DownloaderForm = lazy(() => import('./pages/DownloaderForm'))",
                *lazy_declarations,
                "export default function App() {",
                "  return <Routes>",
                *[f"    {line}" for line in route_lines[:1]],
                '    <Route path="/" element={<Layout />}>',
                "      <Route index element={<HomePage />} />",
                *[
                    f'      <Route path="{path}" element={{<{component} />}} />'
                    for path, component in routes[1:7]
                ],
                '      <Route path="settings" element={<Settings />}>',
                '        <Route path="model" element={<Model />}>',
                '          <Route path="new" element={<ProviderForm />} />',
                '          <Route path=":id" element={<ProviderForm />} />',
                "        </Route>",
                '        <Route path="download" element={<Downloader />}>',
                '          <Route path=":id" element={<DownloaderForm />} />',
                "        </Route>",
                *[
                    f'        <Route path="{path.removeprefix("settings/")}" element={{<{component} />}} />'
                    for path, component in routes[7:13]
                ],
                '        <Route index element={<Navigate to="model" replace />} />',
                '        <Route path="*" element={<NotFoundPage />} />',
                "      </Route>",
                *[
                    f'      <Route path="{path}" element={{<{component} />}} />'
                    for path, component in routes[13:]
                ],
                '      <Route path="*" element={<NotFoundPage />} />',
                "    </Route>",
                "  </Routes>",
                "}",
            ]
        ),
    )
    _write(
        package / "src/pages/HomePage.tsx",
        "export default function HomePage() { return <div>home</div> }",
    )
    _write(
        package / "src/layouts/Layout.tsx",
        "import { Outlet } from 'react-router-dom'; export default function Layout() { return <Outlet /> }",
    )
    _write(
        package / "src/layouts/Settings.tsx",
        "import { Outlet } from 'react-router-dom'; export default function Settings() { return <Outlet /> }",
    )
    _write(
        package / "src/pages/Model.tsx",
        "import { Outlet } from 'react-router-dom'; export default function Model() { return <><Panel /><Outlet /></> }",
    )
    _write(
        package / "src/pages/Downloader.tsx",
        "import { Outlet } from 'react-router-dom'; export default function Downloader() { return <><Panel /><Outlet /></> }",
    )
    _write(
        package / "src/pages/ProviderForm.tsx",
        "export default function ProviderForm() { return <div>provider</div> }",
    )
    _write(
        package / "src/pages/DownloaderForm.tsx",
        "export default function DownloaderForm() { return <div>downloader</div> }",
    )
    for _, component in routes:
        _write(
            package / "src/pages" / f"{component}.tsx",
            f"export default function {component}() {{ return <div>{component}</div> }}",
        )
    _write(
        root / "VideoMemo_extension/package.json",
        json.dumps(
            {"name": "video-extension", "dependencies": {"vue": "3", "vite": "6", "web-ext": "8"}}
        ),
    )
    _write(root / "VideoMemo_extension/src/manifest.ts", "export const manifest = {}")


def _project(root: Path) -> Project:
    return Project(id="p1", name="VideoNote", repo_path=str(root))


def test_video_note_fixture_discovers_logical_pages_and_unsupported_extension(
    tmp_path: Path,
) -> None:
    _react_fixture(tmp_path)

    manifest = ProjectEvidenceService().scan_project(_project(tmp_path))

    assert [(item.package_root, item.support) for item in manifest.packages] == [
        ("VideoMemo_extension", "unsupported"),
        ("VideoMemo_frontend", "supported"),
    ]
    assert len(manifest.candidates) == 19
    model = next(item for item in manifest.candidates if item.title == "Model")
    assert model.route_patterns == ("/settings/model", "/settings/model/:id", "/settings/model/new")
    assert set(model.states) == {"model", "edit", "new"}
    assert all("*" not in route for item in manifest.candidates for route in item.route_patterns)
    assert all("Not Found" not in item.title for item in manifest.candidates)
    assert any("browser extension" in item for item in manifest.diagnostics)
    assert all(
        evidence.confidence in {"high", "medium", "low"}
        for candidate in manifest.candidates
        for evidence in candidate.evidence
    )


def test_empty_shared_styles_are_omitted_but_nonempty_styles_remain_shared_evidence(
    tmp_path: Path,
) -> None:
    _react_fixture(tmp_path)
    style = tmp_path / "VideoMemo_frontend/src/App.css"
    _write(style, "  \n\t")
    service = ProjectEvidenceService()

    empty_style = service.scan_project(_project(tmp_path))

    assert all(
        evidence.path != "VideoMemo_frontend/src/App.css"
        for candidate in empty_style.candidates
        for evidence in candidate.evidence
    )
    assert all(
        evidence.content.strip()
        for candidate in empty_style.candidates
        for evidence in candidate.evidence
    )

    style.write_text(":root { --brand: red; }\n", encoding="utf-8")
    nonempty_style = service.scan_project(_project(tmp_path))
    shared_style_evidence = [
        evidence
        for candidate in nonempty_style.candidates
        for evidence in candidate.evidence
        if evidence.path == "VideoMemo_frontend/src/App.css"
    ]

    assert len(shared_style_evidence) == len(nonempty_style.candidates)
    assert {evidence.kind for evidence in shared_style_evidence} == {"style"}
    assert {evidence.content for evidence in shared_style_evidence} == {":root { --brand: red; }\n"}
    assert {evidence.start_line for evidence in shared_style_evidence} == {1}
    assert {evidence.end_line for evidence in shared_style_evidence} == {1}
    assert len({evidence.evidence_id for evidence in shared_style_evidence}) == 1
    assert empty_style.repository_fingerprint != nonempty_style.repository_fingerprint


def test_scan_is_deterministic_and_hashes_change(tmp_path: Path) -> None:
    _react_fixture(tmp_path)
    service = ProjectEvidenceService()
    first = service.scan_project(_project(tmp_path))
    second = service.scan_project(_project(tmp_path))
    assert first.to_dict() == second.to_dict()

    home = tmp_path / "VideoMemo_frontend/src/pages/HomePage.tsx"
    home.write_text(home.read_text(encoding="utf-8") + "\n// changed", encoding="utf-8")
    changed = service.scan_project(_project(tmp_path))
    before = next(item for item in first.candidates if item.title == "Home Page")
    after = next(item for item in changed.candidates if item.title == "Home Page")
    assert before.candidate_id == after.candidate_id
    assert before.source_hash != after.source_hash

    style = tmp_path / "VideoMemo_frontend/src/index.css"
    _write(style, ":root { --brand: red; }")
    styled = service.scan_project(_project(tmp_path))
    style.write_text(":root { --brand: blue; }", encoding="utf-8")
    restyled = service.scan_project(_project(tmp_path))
    assert styled.repository_fingerprint != restyled.repository_fingerprint


def test_next_app_router_fixture_is_supported(tmp_path: Path) -> None:
    package = tmp_path / "next-app"
    _write(
        package / "package.json",
        json.dumps({"name": "next-app", "dependencies": {"next": "15", "react": "19"}}),
    )
    _write(package / "app/page.tsx", "export default function Home() { return <div>home</div> }")
    _write(
        package / "app/projects/[id]/page.tsx",
        "export default function Project() { return <div>project</div> }",
    )

    manifest = ProjectEvidenceService().scan_project(_project(tmp_path))

    assert {item.route_patterns for item in manifest.candidates} == {("/",), ("/projects/:id",)}
    assert all(item.framework_hint == "next-app-router" for item in manifest.candidates)

    page = package / "app/page.tsx"
    page.write_text("export default function Home() { return <main>home</main> }", encoding="utf-8")
    changed = ProjectEvidenceService().scan_project(_project(tmp_path))
    before_home = next(item for item in manifest.candidates if item.route_patterns == ("/",))
    after_home = next(item for item in changed.candidates if item.route_patterns == ("/",))
    assert before_home.source_hash != after_home.source_hash


def test_admin_demo_vue_router_pages_are_supported() -> None:
    repo = Path(__file__).resolve().parents[2] / "examples/admin-demo"

    manifest = ProjectEvidenceService().scan_project(_project(repo))

    assert [(item.package_root, item.support) for item in manifest.packages] == [
        ("frontend", "supported")
    ]
    assert {item.route_patterns for item in manifest.candidates} == {
        ("/dashboard",),
        ("/orders",),
        ("/users",),
    }
    assert {item.primary_source_path for item in manifest.candidates} == {
        "frontend/src/pages/DashboardPage.vue",
        "frontend/src/pages/OrdersPage.vue",
        "frontend/src/pages/UsersPage.vue",
    }
    assert all(item.framework_hint == "vue-router" for item in manifest.candidates)
    assert all(
        any(evidence.kind == "vue-router-route" for evidence in item.evidence)
        for item in manifest.candidates
    )
    assert all("frontend/src/App.vue" in item.layout_paths for item in manifest.candidates)
    assert all(
        any(evidence.path == "frontend/src/styles.css" for evidence in item.evidence)
        for item in manifest.candidates
    )


def test_vue_router_nested_routes_and_dynamic_diagnostics(tmp_path: Path) -> None:
    package = tmp_path / "frontend"
    _write(
        package / "package.json",
        json.dumps(
            {
                "name": "vue-app",
                "dependencies": {"vue": "3", "vue-router": "4", "vite": "6"},
            }
        ),
    )
    _write(
        package / "src/router.ts",
        "\n".join(
            (
                "import { createRouter, createWebHistory } from 'vue-router'",
                "import SettingsPage from './pages/SettingsPage.vue'",
                "const DYNAMIC_PATH = '/dynamic'",
                "createRouter({",
                "  history: createWebHistory(),",
                "  routes: [",
                "    { path: '/', redirect: '/settings' },",
                "    { path: '/settings', component: SettingsPage, children: [",
                "      { path: 'profile', component: () => import('./pages/ProfilePage.vue') },",
                "    ] },",
                "    { path: DYNAMIC_PATH, component: SettingsPage },",
                "    { path: '/:pathMatch(.*)*', component: SettingsPage },",
                "  ],",
                "})",
            )
        ),
    )
    _write(package / "src/App.vue", "<template><RouterView /></template>")
    _write(package / "src/pages/SettingsPage.vue", "<template><RouterView /></template>")
    _write(package / "src/pages/ProfilePage.vue", "<template><h1>Profile</h1></template>")

    manifest = ProjectEvidenceService().scan_project(_project(tmp_path))

    assert {
        item.route_patterns for item in manifest.candidates if item.action != "unsupported"
    } == {
        ("/settings",),
        ("/settings/profile",),
    }
    profile = next(
        item for item in manifest.candidates if item.route_patterns == ("/settings/profile",)
    )
    assert "frontend/src/pages/SettingsPage.vue" in profile.layout_paths
    assert all(
        "pathMatch" not in route for item in manifest.candidates for route in item.route_patterns
    )
    assert any(
        "not statically evaluable" in diagnostic
        for item in manifest.candidates
        for diagnostic in item.diagnostics
    )


def test_react_router_aliases_and_dynamic_path_diagnostics(tmp_path: Path) -> None:
    package = tmp_path / "frontend"
    _write(
        package / "package.json",
        json.dumps(
            {
                "name": "frontend",
                "dependencies": {"react": "19", "react-router-dom": "7", "vite": "6"},
            }
        ),
    )
    _write(
        package / "src/App.tsx",
        "\n".join(
            (
                "import { Routes as AppRoutes, Route as AppRoute } from 'react-router-dom'",
                "import Home from './Home'",
                "const HOME = '/home'",
                "export default function App() {",
                "  return <AppRoutes>",
                '    <AppRoute path="/" element={<Home />} />',
                "    <AppRoute path={HOME} element={<Home />} />",
                "  </AppRoutes>",
                "}",
            )
        ),
    )
    _write(package / "src/Home.tsx", "export default function Home() { return <div>home</div> }")

    manifest = ProjectEvidenceService().scan_project(_project(tmp_path))

    assert any(candidate.route_patterns == ("/",) for candidate in manifest.candidates)
    assert all(
        "{HOME}" not in route for item in manifest.candidates for route in item.route_patterns
    )
    assert any(
        "not statically evaluable" in diagnostic
        for item in manifest.candidates
        for diagnostic in item.diagnostics
    )
    parser_evidence = [
        evidence
        for item in manifest.candidates
        for evidence in item.evidence
        if evidence.kind == "parser"
    ]
    assert parser_evidence
    assert all(evidence.confidence == "low" for evidence in parser_evidence)
    assert all(evidence.diagnostic for evidence in parser_evidence)


def test_repository_boundary_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "evidence-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "escape.tsx").symlink_to(outside)

    with pytest.raises(RepositoryBoundaryError):
        RepositoryBoundary.from_repo_path(str(root)).iter_files()


def test_repository_boundary_ignores_only_root_generated_prototypes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    generated = root / "prototypes" / "prototype-1" / "version-1" / "index.html"
    generated.parent.mkdir(parents=True)
    generated.write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
    nested_source = root / "src" / "prototypes" / "Page.tsx"
    nested_source.parent.mkdir(parents=True)
    nested_source.write_text("export const Page = 1;\n", encoding="utf-8")

    boundary = RepositoryBoundary.from_repo_path(str(root))
    relative_files = {boundary.relative_path(path) for path in boundary.iter_files()}

    assert "prototypes/prototype-1/version-1/index.html" not in relative_files
    assert "src/prototypes/Page.tsx" in relative_files


def test_invalid_root_is_a_typed_evidence_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectEvidenceError, match="not a directory"):
        ProjectEvidenceService().scan_project(_project(tmp_path / "missing"))
