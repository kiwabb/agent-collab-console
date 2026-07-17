from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP_ROOT = REPO_ROOT / "backend" / "app"
BACKEND_RUNTIME_ASSETS = (
    BACKEND_APP_ROOT / "runtime_assets" / "prototype_public_runtime.js",
    BACKEND_APP_ROOT / "runtime_assets" / "prototype_renderer_worker.mjs",
)
BACKEND_GENERATION_SUPPORT_SOURCES = (
    BACKEND_APP_ROOT / "adapters" / "structured_prototype_store.py",
    BACKEND_APP_ROOT / "application" / "prototype_ui_engineer_runner.py",
    BACKEND_APP_ROOT / "application" / "structured_prototype_service.py",
    BACKEND_APP_ROOT / "domain" / "structured_prototype_generation.py",
    BACKEND_APP_ROOT / "interfaces" / "structured_prototype_generation_api.py",
)
FRONTEND_STUDIO_ROOT = REPO_ROOT / "frontend" / "src" / "features" / "prototype" / "structured"
FRONTEND_RUNTIME_FEATURE_ROOT = (
    REPO_ROOT / "frontend" / "src" / "features" / "prototype" / "runtime"
)
FRONTEND_APP_ROOT = REPO_ROOT / "frontend" / "src" / "app"
FRONTEND_RUNTIME_ROOT = REPO_ROOT / "frontend" / "scripts"
FRONTEND_I18N_SOURCES = (
    REPO_ROOT / "frontend" / "src" / "lib" / "i18n" / "en-US.ts",
    REPO_ROOT / "frontend" / "src" / "lib" / "i18n" / "zh-CN.ts",
)

FORBIDDEN_DOMAIN_PATTERNS = {
    "procurement identifier": re.compile(r"procurement", re.IGNORECASE),
    "purchase identifier": re.compile(r"purchase", re.IGNORECASE),
    "procurement copy": re.compile(r"采购"),
    "approval status copy": re.compile(r"待审批|审批通过|已通过"),
    "fixed demo brand": re.compile(r"\bOrion\b"),
    "fixed currency presentation": re.compile(r"(?:¥|\bCNY\b|\bRMB\b)"),
    "fixed workflow participant role": re.compile(
        r"(?:"
        r"[\"'](?:applicant|requester|manager|approver)[\"']"
        r"|(?<![A-Za-z0-9])"
        r"(?:(?:applicant|requester|manager|approver)(?:[_-]?role)"
        r"|role(?:[_-]?(?:applicant|requester|manager|approver)))"
        r"(?![A-Za-z0-9])"
        r")",
        re.IGNORECASE,
    ),
    "fixed approval workflow": re.compile(
        r"(?<![A-Za-z0-9])approval(?![_ -]?policy\b)(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    "fixed requests route": re.compile(
        r"(?P<quote>[\"'`])/requests(?:[/?#][^\"'`\s]*)?(?P=quote)",
        re.IGNORECASE,
    ),
}
UNLOCALIZED_CHINESE = re.compile(r"[\u3400-\u9fff]")

PROCUREMENT_FIXTURE_IMPORT = re.compile(
    r"(?:from\s+|import\s*\(\s*)[\"'][^\"']*procurement(?:Document)?Fixture[\"']",
    re.IGNORECASE,
)


def _production_generation_sources() -> tuple[Path, ...]:
    backend_sources = sorted(
        {
            *BACKEND_APP_ROOT.rglob("structured_prototype_generation*.py"),
            *BACKEND_GENERATION_SUPPORT_SOURCES,
        }
    )
    frontend_sources = sorted(
        path
        for path in FRONTEND_STUDIO_ROOT.iterdir()
        if path.suffix in {".ts", ".tsx"}
    )
    runtime_feature_sources = sorted(
        path
        for path in FRONTEND_RUNTIME_FEATURE_ROOT.iterdir()
        if path.suffix in {".ts", ".tsx"}
    )
    prototype_route_sources = sorted(
        path
        for path in FRONTEND_APP_ROOT.rglob("*.tsx")
        if "prototype" in path.parts or "prototypes" in path.parts
    )
    runtime_sources = sorted(FRONTEND_RUNTIME_ROOT.glob("prototype-*.ts"))
    return (
        tuple(
            backend_sources
            + frontend_sources
            + runtime_feature_sources
            + prototype_route_sources
            + runtime_sources
        )
        + BACKEND_RUNTIME_ASSETS
        + FRONTEND_I18N_SOURCES
    )


def _forbidden_domain_labels(line: str) -> tuple[str, ...]:
    return tuple(
        label for label, pattern in FORBIDDEN_DOMAIN_PATTERNS.items() if pattern.search(line)
    )


def test_forbidden_domain_patterns_target_fixed_workflow_coupling() -> None:
    coupled_sources = (
        'role = "applicant"',
        'actor = "requester"',
        'role_key = "manager"',
        'next_role = "approver"',
        'status = "approval_pending"',
        '@router.get("/requests")',
        'route = "/requests/{request_id}"',
        'route = "/requests?status=open"',
    )
    for source in coupled_sources:
        assert _forbidden_domain_labels(source), source

    generic_technical_sources = (
        "manager = process_manager",
        "with context_manager():",
        'approval_policy = "never"',
        'route = "/api/runtime/requests"',
        'requester_factory = build_http_client()',
    )
    for source in generic_technical_sources:
        assert not _forbidden_domain_labels(source), source


def test_generation_source_scan_covers_durable_runtime_paths_without_fixtures() -> None:
    sources = set(_production_generation_sources())
    required_sources = {
        *BACKEND_GENERATION_SUPPORT_SOURCES,
        BACKEND_APP_ROOT / "application" / "structured_prototype_generation_runtime.py",
        BACKEND_APP_ROOT / "application" / "structured_prototype_generation_service.py",
    }

    assert required_sources <= sources
    assert all("tests" not in path.relative_to(REPO_ROOT).parts for path in sources)


def test_generation_production_sources_are_free_of_procurement_demo_coupling() -> None:
    sources = _production_generation_sources()
    assert sources, "expected structured prototype generation production sources"

    violations: list[str] = []
    for path in sources:
        is_i18n_source = path in FRONTEND_I18N_SOURCES
        inside_structured_i18n_entry = False
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if is_i18n_source:
                if re.match(r'^\s*"[^"]+":', line):
                    inside_structured_i18n_entry = '"prototype.structured.' in line
                if not inside_structured_i18n_entry:
                    continue
            if PROCUREMENT_FIXTURE_IMPORT.search(line):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_number}: procurement fixture import"
                )
            if not is_i18n_source and UNLOCALIZED_CHINESE.search(line):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_number}: unlocalized Chinese copy"
                )
            for label in _forbidden_domain_labels(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {label}")

    assert not violations, "production generation paths contain demo coupling:\n" + "\n".join(
        violations
    )
