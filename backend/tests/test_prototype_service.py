"""Prototype service tests.

We deliberately stay off the network — every test patches
`PrototypeService._stream_html` (the actual HTTP SSE parser) with an
async generator that yields a fixed chunk sequence, so the service-level
prompt assembly, version bookkeeping, code-fence stripping, and disk
mirror are exercised without needing a live LLM endpoint.

Disk-touching tests are tagged `@pytest.mark.slow` per the PRD, so the
default `pytest -v` run stays fast.
"""

from __future__ import annotations  # noqa: I001

import shutil
import subprocess
from pathlib import Path
from typing import AsyncGenerator, AsyncIterator  # noqa: UP035

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.prototype_service import (
    PrototypeError,
    PrototypeService,
    RuntimePrototypeEvidence,
    StreamEvent,  # noqa: F401
    _stream_html,
    build_code_backed_brief,
    compact_code_source_excerpt,
    build_html_system_prompt,
    build_iteration_system_prompt,
    is_complete_html_document,
    strip_markdown_fence,
)
from app.application.code_prototype_discovery import (
    CodePrototypeCandidate,
    CodePrototypeDiscoveryService,
)
from app.application.runtime_catalog_service import RuntimeCatalogService  # noqa: F401
from app.application.runtime_prototype_capture import resolve_runtime_route
from app.domain.models import Project, PrototypeVersion, RuntimeExecutorConfig
from app.application.llm_runner import StreamingPlanContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path: Path) -> AsyncGenerator[AsyncSQLiteStore, None]:
    s = AsyncSQLiteStore(tmp_path / "test.db")
    await s._init_db()
    try:
        yield s
    finally:
        await s.close()


@pytest.fixture
def fake_catalog_service():
    """A minimal runtime_catalog_service whose `load_catalog()` returns one
    enabled executor with api_endpoint+api_key. We never call it from
    `_stream_html` (we monkeypatch that), but the prototype service still
    calls `resolve_streaming_context` to pick a model for the SSE `meta`
    event."""

    class _Fake:
        async def load_catalog(self):
            from app.domain.models import RuntimeCatalog

            return RuntimeCatalog(
                executors=[
                    RuntimeExecutorConfig(
                        id="claude",
                        label="claude",
                        enabled=True,
                        api_endpoint="https://example.invalid",
                        api_key="sk-test",
                        default_model="claude-test-model",
                    )
                ]
            )

    return _Fake()


@pytest.fixture
def svc(store: AsyncSQLiteStore, fake_catalog_service) -> PrototypeService:
    return PrototypeService(store=store, runtime_catalog_service=fake_catalog_service)


def _project_repo_path(project: Project) -> Path:
    assert project.repo_path is not None
    return Path(project.repo_path)


def _versions(detail: dict[str, object]) -> list[PrototypeVersion]:
    versions = detail["versions"]
    assert isinstance(versions, list)
    assert all(isinstance(version, PrototypeVersion) for version in versions)
    return versions


def _candidate_items(preview: dict[str, object]) -> list[dict[str, object]]:
    candidates = preview["candidates"]
    assert isinstance(candidates, list)
    assert all(isinstance(item, dict) for item in candidates)
    return [{str(key): value for key, value in item.items()} for item in candidates]


def _make_git_repo(path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
async def project(store: AsyncSQLiteStore, tmp_path: Path) -> Project:
    repo = _make_git_repo(tmp_path / "demo")
    from datetime import datetime

    p = Project(
        id="proj-1",
        name="demo",
        repo_path=str(repo),
        default_branch="main",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await store.save_project(p)
    return p


# ---------------------------------------------------------------------------
# Pure-function tests (no DB, no IO)
# ---------------------------------------------------------------------------


def test_strip_markdown_fence_handles_known_shapes():
    assert (
        strip_markdown_fence("```html\n<!DOCTYPE html>\n<html></html>\n```")
        == "<!DOCTYPE html>\n<html></html>"
    )
    assert strip_markdown_fence("```HTML\n<body></body>\n```") == "<body></body>"
    # Already-clean HTML stays untouched.
    raw = "<!DOCTYPE html>\n<html></html>"
    assert strip_markdown_fence(raw) == raw
    # Truncated ```html with no closing fence -> stripped leading fence line.
    truncated = "```html\n<!DOCTYPE html>\n<html></html>"
    assert strip_markdown_fence(truncated).startswith("<!DOCTYPE html>")


def test_is_complete_html_document_requires_doctype_and_closing_html():
    assert is_complete_html_document("<!DOCTYPE html><html><body>x</body></html>")
    assert not is_complete_html_document("<html><body>x</body></html>")
    assert not is_complete_html_document("<!DOCTYPE html><html><body>x</body>")
    assert not is_complete_html_document("<!DOCTYPE html><html><body>x</")


def test_build_html_system_prompt_includes_brief_and_doctype_anchor():
    p = build_html_system_prompt("a SaaS pricing page, three cards")
    assert "<!DOCTYPE html>" in p
    assert "a SaaS pricing page" in p
    assert "Tailwind" in p  # constraint sentence


def test_build_iteration_system_prompt_carries_latest_html_and_instruction():
    latest = "<!DOCTYPE html><html><body><h1>v1</h1></body></html>"
    p = build_iteration_system_prompt(latest, "make headings bigger")
    assert latest in p
    assert "make headings bigger" in p
    assert "<!DOCTYPE html>" in p


def test_build_code_backed_brief_prioritizes_complete_compact_output(project: Project):
    candidate = CodePrototypeCandidate(
        id="next-app-router--help",
        title="Help",
        route="/help",
        kind="page",
        framework_hint="next-app-router",
        source_paths=["frontend/src/app/help/page.tsx"],
        primary_source_path="frontend/src/app/help/page.tsx",
        source_hash="sha256:test",
        source_excerpt="export default function Page() { return <HelpPage /> }",
        signals=["app-router-page"],
    )

    brief = build_code_backed_brief(candidate, project)

    assert "Prefer a compact complete prototype" in brief
    assert "finish within the response budget" in brief
    assert "representative loading/empty/error states" in brief
    assert "ending with </html>" in brief
    assert "80-140 lines" in brief
    assert "representative first-screen slice" in brief


def test_build_code_backed_brief_uses_safe_runtime_evidence(project: Project):
    candidate = CodePrototypeCandidate(
        id="next-app-router--help",
        title="Help",
        route="/help",
        kind="page",
        framework_hint="next-app-router",
        source_paths=["frontend/src/app/help/page.tsx"],
        primary_source_path="frontend/src/app/help/page.tsx",
        source_hash="sha256:test",
        source_excerpt="export default function Page() { return <HelpPage /> }",
        signals=["app-router-page"],
    )
    evidence = RuntimePrototypeEvidence.from_payload(
        {
            "attempted_url": "http://127.0.0.1:3000/help",
            "final_url": "http://127.0.0.1:3000/help",
            "success": True,
            "title": "Help Center",
            "viewport": {"width": 1440, "height": 900},
            "visible_text_excerpt": "Help Center\nSearch docs\nCommon setup questions",
            "structure_summary": "headings: Help Center; buttons: Search, Open ticket",
            "console_errors": ["hydration warning"],
            "screenshot_path": ".agent-collab/prototypes/captures/help.png",
            "cookies": "secret-cookie",
            "localStorage": {"token": "secret-token"},
            "html": "<html>full page html should not be accepted</html>",
        }
    )
    assert evidence is not None

    brief = build_code_backed_brief(candidate, project, evidence)

    assert "Runtime evidence priority" in brief
    assert "Capture status: success" in brief
    assert "Help Center" in brief
    assert "Common setup questions" in brief
    assert "secret-cookie" not in brief
    assert "secret-token" not in brief
    assert "full page html" not in brief


def test_build_code_backed_brief_failed_runtime_evidence_falls_back(project: Project):
    candidate = CodePrototypeCandidate(
        id="next-app-router--settings",
        title="Settings",
        route="/settings",
        kind="page",
        framework_hint="next-app-router",
        source_paths=["frontend/src/app/settings/page.tsx"],
        primary_source_path="frontend/src/app/settings/page.tsx",
        source_hash="sha256:test",
        source_excerpt="export default function Page() { return <SettingsPage /> }",
        signals=["app-router-page"],
    )
    evidence = RuntimePrototypeEvidence(
        attempted_url="http://127.0.0.1:3000/settings",
        success=False,
        failure_reason="connection refused",
    )

    brief = build_code_backed_brief(candidate, project, evidence)

    assert "Capture status: failed or unavailable" in brief
    assert "fall back to the source excerpt" in brief
    assert "connection refused" in brief
    assert "Source excerpt:" in brief


def test_build_code_backed_brief_includes_user_edited_candidate_brief(project: Project):
    candidate = CodePrototypeCandidate(
        id="next-app-router--approvals",
        title="Approvals",
        route="/approvals",
        kind="page",
        framework_hint="next-app-router",
        source_paths=["frontend/src/app/approvals/page.tsx"],
        primary_source_path="frontend/src/app/approvals/page.tsx",
        source_hash="sha256:test",
        source_excerpt="export default function Page() { return <main>Approvals</main> }",
        signals=["app-router-page"],
    )

    brief = build_code_backed_brief(
        candidate,
        project,
        editable_brief_override="Focus the prototype on the approval queue and compact reviewer actions.",
    )

    assert "User-edited candidate brief override" in brief
    assert "approval queue" in brief
    assert "Use this edited brief as the primary page intent" in brief
    assert "Source excerpt:" in brief


def test_compact_code_source_excerpt_preserves_high_signal_ui_lines():
    source = (
        "--- frontend/src/features/agents/AgentLibraryPage.tsx ---\n"
        + "\n".join(f"import {{ Thing{i} }} from './thing-{i}';" for i in range(200))
        + "\nexport function AgentLibraryPage() {\n"
        + "  const [loading, setLoading] = useState(true);\n"
        + "  const [error, setError] = useState<string | null>(null);\n"
        + "  return (\n"
        + "    <PageFrame title={t(\"agents.pageTitle\")} description={t(\"agents.pageSubtitle\")}>\n"
        + "      {loading && <InteractionEmptyState tone=\"loading\" title={t(\"agents.loadingTitle\")} />}\n"
        + "      {error && <div className=\"rounded-md border border-error\">{error}</div>}\n"
        + "      <Button>{t(\"agents.new\")}</Button>\n"
        + "    </PageFrame>\n"
        + "  );\n"
        + "}\n"
    )

    compacted = compact_code_source_excerpt(source)

    assert len(compacted) < len(source)
    assert "Source excerpt compacted for generation" in compacted
    assert "AgentLibraryPage" in compacted
    assert "InteractionEmptyState" in compacted
    assert "agents.pageTitle" in compacted
    assert "border-error" in compacted


def test_resolve_runtime_route_uses_deterministic_dynamic_placeholders():
    issue = resolve_runtime_route("http://localhost:4000", "/issues/:id/workflow")
    workspace = resolve_runtime_route("http://localhost:4000/", "/workspaces/:wsId")
    next_dynamic = resolve_runtime_route("http://localhost:4000", "/projects/[projectId]")

    assert issue.attempted_url == "http://localhost:4000/issues/demo-id/workflow"
    assert workspace.attempted_url == "http://localhost:4000/workspaces/demo-ws"
    assert next_dynamic.attempted_url == "http://localhost:4000/projects/demo"


# ---------------------------------------------------------------------------
# CRUD pass-throughs (no LLM involved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_stores_prototype_and_seed_version(svc: PrototypeService, project: Project):
    proto = await svc.create(project.id, "Pricing page", "Three-card pricing layout")
    assert proto.id
    assert proto.title == "Pricing page"
    assert proto.current_version == 0
    # Seed row carries the brief; version list (UI surface) hides it.
    detail = await svc.get_with_versions(proto.id)
    assert detail["versions"] == []
    seed = await svc.store.load_prototype_version(proto.id, 0)
    assert seed is not None
    assert seed.instruction == "Three-card pricing layout"


@pytest.mark.asyncio
async def test_create_validates_brief_and_title(svc: PrototypeService, project: Project):
    with pytest.raises(PrototypeError, match="brief is required"):
        await svc.create(project.id, "t", "   ")
    with pytest.raises(PrototypeError, match="project not found"):
        await svc.create("no-such-project", "t", "b")


@pytest.mark.asyncio
async def test_list_and_delete_round_trip(svc: PrototypeService, project: Project):
    p1 = await svc.create(project.id, "A", "brief a")
    p2 = await svc.create(project.id, "B", "brief b")
    listed = await svc.list_for_project(project.id)
    assert {p.id for p in listed} == {p1.id, p2.id}
    await svc.delete(p1.id)
    listed_after = await svc.list_for_project(project.id)
    assert [p.id for p in listed_after] == [p2.id]


# ---------------------------------------------------------------------------
# Streaming generation (monkeypatched LLM)
# ---------------------------------------------------------------------------


async def _fake_stream_html_chunks(prompt: str, ctx) -> AsyncIterator[str]:  # noqa: ARG001, RUF100
    # Mirror what a real LLM would do: start with <!DOCTYPE html>, end with
    # </html>. We DO include a stray markdown fence to exercise strip_markdown_fence.
    yield "```html\n"
    yield "<!DOCTYPE html>\n"
    yield "<html><body><h1>Pricing</h1>"
    yield "<p>three cards</p></body></html>\n"
    yield "```\n"


async def _collect(svc: PrototypeService, prototype_id: str, instruction: str | None):
    return [ev async for ev in svc.stream_events(prototype_id, instruction)]


class _FakePrototypeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b""


class _NoisyPrototypeStreamClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers=None, json=None):  # noqa: ANN001, RUF100
        return _FakePrototypeStreamResponse(
            [
                "data: []",
                "data: not json",
                'data: {"type":"content_block_delta","delta":"bad"}',
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"<!DOCTYPE html>"}}',
                'data: {"type":"message_stop"}',
            ]
        )


@pytest.mark.asyncio
async def test_stream_html_skips_non_object_and_malformed_sse_events(monkeypatch):
    def fake_http_client(timeout_s: float):
        return _NoisyPrototypeStreamClient()

    monkeypatch.setattr("app.application.prototype_service._llm_http_client", fake_http_client)

    chunks = [
        chunk
        async for chunk in _stream_html(
            "prompt",
            StreamingPlanContext(
                executor_id="claude",
                executor_label="Claude",
                model="claude-test",
                endpoint="https://example.test",
                api_key="secret",
                max_tokens=1024,
                timeout_s=10,
            ),
        )
    ]

    assert chunks == ["<!DOCTYPE html>"]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_generate_v1_writes_db_and_disk_mirror(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    proto = await svc.create(project.id, "Pricing", "SaaS pricing page")

    events = await _collect(svc, proto.id, None)
    by_type = [ev.event for ev in events]
    assert by_type[0] == "meta"
    assert "delta" in by_type
    assert by_type[-1] == "done"

    done = events[-1].data
    assert done["version_no"] == 1
    # Fence is stripped before persistence.
    assert done["html"].lstrip().startswith("<!DOCTYPE html>")
    assert done["html"].rstrip().endswith("</html>")
    assert "<meta" not in done["html"]  # nothing extra crept in
    assert "```" not in done["html"]

    # DB: current_version bumped, version row has the cleaned HTML.
    reloaded = await svc.get(proto.id)
    assert reloaded.current_version == 1
    v1 = await svc.store.load_prototype_version(proto.id, 1)
    assert v1 is not None
    assert v1.html == done["html"]
    assert v1.disk_path is not None
    # Disk mirror exists under <repo>/.agent-collab/prototypes/<id>/v1/index.html
    disk = Path(v1.disk_path)
    assert disk.exists()
    assert disk.read_text(encoding="utf-8") == done["html"]
    assert disk.parent.name == "v1"
    # And it lives under the project's repo_path.
    assert str(disk).startswith(project.repo_path)


@pytest.mark.asyncio
@pytest.mark.slow
async def test_iterate_with_instruction_produces_v2(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    proto = await svc.create(project.id, "Pricing", "v1 brief")
    await _collect(svc, proto.id, None)  # → v1

    async def fake_iter(prompt, ctx):  # noqa: ARG001, RUF100
        # Iteration should be a refinement of the prior HTML; pretend the
        # model kept the structure and added a footer.
        yield "<!DOCTYPE html>\n<html><body>"
        yield "<h1>Pricing v2</h1>"
        yield "<footer>refined</footer></body></html>"

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        fake_iter,
    )

    events = await _collect(svc, proto.id, "make heading bigger")
    done = events[-1].data
    assert done["version_no"] == 2
    assert "v2" in done["html"]
    assert "refined" in done["html"]

    detail = await svc.get_with_versions(proto.id)
    assert [v.version_no for v in _versions(detail)] == [1, 2]
    reloaded = await svc.get(proto.id)
    assert reloaded.current_version == 2


@pytest.mark.asyncio
async def test_iterate_without_prior_version_yields_error(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    proto = await svc.create(project.id, "Pricing", "v1 brief")
    events = await _collect(svc, proto.id, "change colors")
    assert events[-1].event == "error"
    assert "no prior version" in events[-1].data["message"]
    # DB untouched: no v2 row written, current_version still 0.
    reloaded = await svc.get(proto.id)
    assert reloaded.current_version == 0


@pytest.mark.asyncio
async def test_empty_llm_response_yields_error_and_no_db_write(
    svc: PrototypeService, project: Project, monkeypatch
):
    async def empty_stream(prompt, ctx):  # noqa: ARG001, RUF100
        if False:
            yield ""  # pragma: no cover - keep this a generator

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        empty_stream,
    )
    proto = await svc.create(project.id, "Pricing", "v1 brief")
    events = await _collect(svc, proto.id, None)
    assert events[-1].event == "error"
    assert events[-1].data["message"] == "LLM returned empty HTML"
    reloaded = await svc.get(proto.id)
    assert reloaded.current_version == 0


@pytest.mark.asyncio
async def test_incomplete_html_response_yields_error_and_no_db_write(
    svc: PrototypeService, project: Project, monkeypatch
):
    async def truncated_stream(prompt, ctx):  # noqa: ARG001, RUF100
        yield "<!DOCTYPE html><html><body><h1>Cut off</h1></"

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        truncated_stream,
    )
    proto = await svc.create(project.id, "Help", "help page")
    events = await _collect(svc, proto.id, None)
    assert events[-1].event == "error"
    assert "incomplete HTML" in events[-1].data["message"]
    reloaded = await svc.get(proto.id)
    assert reloaded.current_version == 0
    assert await svc.store.load_prototype_version(proto.id, 1) is None


@pytest.mark.asyncio
async def test_stream_aborts_on_runtime_error(svc: PrototypeService, project: Project, monkeypatch):
    async def boom(prompt, ctx):  # noqa: ARG001, RUF100
        raise RuntimeError("upstream 502")
        yield ""  # pragma: no cover - keeps it a generator

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        boom,
    )
    proto = await svc.create(project.id, "Pricing", "v1 brief")
    events = await _collect(svc, proto.id, None)
    assert events[-1].event == "error"
    assert "502" in events[-1].data["message"]
    reloaded = await svc.get(proto.id)
    assert reloaded.current_version == 0


# ---------------------------------------------------------------------------
# Project-level batch regenerate
# ---------------------------------------------------------------------------


async def _collect_batch(svc: PrototypeService, project_id: str):
    return [ev async for ev in svc.regenerate_all_stream(project_id)]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_regenerate_all_emits_done_per_prototype_and_empty_failed(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    p1 = await svc.create(project.id, "Pricing", "brief 1")
    p2 = await svc.create(project.id, "Landing", "brief 2")

    events = await _collect_batch(svc, project.id)
    types = [ev.event for ev in events]

    # Envelope: batch_meta first, all_done last.
    assert types[0] == "batch_meta"
    assert events[0].data == {"count": 2}
    assert types[-1] == "all_done"

    # One prototype_start per prototype; list_for_project orders by
    # updated_at DESC, which is non-deterministic for ties within the same
    # second, so we only assert membership here.
    starts = [ev for ev in events if ev.event == "prototype_start"]
    assert {ev.data["prototype_id"] for ev in starts} == {p1.id, p2.id}
    for ev in starts:
        assert ev.data["title"]

    dones = [ev for ev in events if ev.event == "prototype_done"]
    assert {ev.data["prototype_id"] for ev in dones} == {p1.id, p2.id}
    for ev in dones:
        assert ev.data["version_no"] == 1
        assert ev.data["html"].lstrip().startswith("<!DOCTYPE html>")
        assert ev.data["disk_path"]

    deltas = [ev for ev in events if ev.event == "prototype_delta"]
    assert deltas, "expected per-prototype deltas to be forwarded"
    assert all(d.data["prototype_id"] in {p1.id, p2.id} for d in deltas)

    assert not [ev for ev in events if ev.event == "prototype_error"]

    summary = events[-1].data
    assert sorted(summary["ok"]) == sorted([p1.id, p2.id])
    assert summary["failed"] == []

    # Both prototypes now have a v1 row.
    for proto in (p1, p2):
        reloaded = await svc.get(proto.id)
        assert reloaded.current_version == 1


@pytest.mark.asyncio
@pytest.mark.slow
async def test_regenerate_all_skips_failure_and_continues_with_remaining(
    svc: PrototypeService, project: Project, monkeypatch
):
    p1 = await svc.create(project.id, "Boom", "brief 1")
    p2 = await svc.create(project.id, "OK", "brief 2")
    p3 = await svc.create(project.id, "AlsoOK", "brief 3")

    # First call: boom. Subsequent calls: the regular happy-path fake.
    call_count = {"n": 0}

    async def conditional_stream(prompt, ctx):  # noqa: ARG001, RUF100
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("upstream 502")
            yield ""  # pragma: no cover - keeps it a generator
        async for chunk in _fake_stream_html_chunks(prompt, ctx):
            yield chunk

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        conditional_stream,
    )

    events = await _collect_batch(svc, project.id)
    summary = events[-1].data
    ok_set = set(summary["ok"])
    failed_set = {f["prototype_id"] for f in summary["failed"]}
    # `conditional_stream` makes the first call (whichever prototype that
    # is, in list_for_project's updated_at-DESC order) fail. The other two
    # succeed. We don't pin down which id is which — only the cardinality
    # and disjointness, since the store's tie-break on identical updated_at
    # is non-deterministic.
    assert ok_set | failed_set == {p1.id, p2.id, p3.id}
    assert ok_set & failed_set == set()
    assert len(summary["failed"]) == 1
    assert "502" in summary["failed"][0]["message"]

    # Error event appeared once, before the remaining two prototypes had
    # a chance to start.
    error_events = [ev for ev in events if ev.event == "prototype_error"]
    assert len(error_events) == 1
    assert error_events[0].data["prototype_id"] == next(iter(failed_set))

    # All three prototypes were attempted (start + per-prototype events).
    starts = [ev for ev in events if ev.event == "prototype_start"]
    assert {ev.data["prototype_id"] for ev in starts} == {p1.id, p2.id, p3.id}

    # The failed prototype stays at current_version=0; the survivors got v1.
    failed_id = next(iter(failed_set))
    survivors = {p1.id, p2.id, p3.id} - {failed_id}
    assert (await svc.get(failed_id)).current_version == 0
    for sid in survivors:
        assert (await svc.get(sid)).current_version == 1


@pytest.mark.asyncio
async def test_regenerate_all_with_no_prototypes_emits_zero_summary(
    svc: PrototypeService, project: Project
):
    events = await _collect_batch(svc, project.id)
    types = [ev.event for ev in events]
    assert types == ["batch_meta", "all_done"]
    assert events[0].data == {"count": 0}
    assert events[-1].data == {"ok": [], "failed": []}


@pytest.mark.asyncio
async def test_regenerate_all_raises_for_unknown_project(svc: PrototypeService):
    from app.application.prototype_service import PrototypeError

    with pytest.raises(PrototypeError, match="project not found"):
        async for _ in svc.regenerate_all_stream("no-such-project"):
            pass


# ---------------------------------------------------------------------------
# Code-driven discovery + generation
# ---------------------------------------------------------------------------


def _write_page(repo: Path, rel: str, body: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_code_discovery_detects_supported_pages_and_ignores_heavy_dirs(project: Project):
    repo = Path(project.repo_path)
    _write_page(repo, "frontend/src/app/projects/[id]/prototypes/page.tsx", "export default function ProjectPrototypesPage() { return <main /> }")
    _write_page(repo, "pages/api/hello.tsx", "export default function Api() { return null }")
    _write_page(repo, "node_modules/pkg/src/app/ignored/page.tsx", "export default function Ignored() { return null }")
    _write_page(repo, "src/features/audit/AuditPage.tsx", "export function AuditPage() { return <section /> }")

    candidates = CodePrototypeDiscoveryService().scan_project(project)
    by_route = {candidate.route: candidate for candidate in candidates}

    assert "/projects/:id/prototypes" in by_route
    assert by_route["/projects/:id/prototypes"].framework_hint == "next-app-router"
    assert by_route["/projects/:id/prototypes"].primary_source_path == "frontend/src/app/projects/[id]/prototypes/page.tsx"
    assert any(candidate.route == "/audit/audit" for candidate in candidates)
    assert not any("node_modules" in candidate.primary_source_path for candidate in candidates)
    assert not any(candidate.route.startswith("/api") for candidate in candidates)


def test_code_discovery_includes_direct_local_import_context(project: Project):
    repo = Path(project.repo_path)
    _write_page(
        repo,
        "frontend/src/app/help/page.tsx",
        (
            "import { HelpPage } from '@/features/help/HelpPage';\n"
            "export default function Page() { return <HelpPage /> }\n"
        ),
    )
    help_component = repo / "frontend/src/features/help/HelpPage.tsx"
    _write_page(
        repo,
        "frontend/src/features/help/HelpPage.tsx",
        "export function HelpPage() { return <main><h1>Real Help Structure</h1></main> }",
    )

    candidate = CodePrototypeDiscoveryService().scan_project(project)[0]
    assert candidate.primary_source_path == "frontend/src/app/help/page.tsx"
    assert candidate.source_paths == [
        "frontend/src/app/help/page.tsx",
        "frontend/src/features/help/HelpPage.tsx",
    ]
    assert "Real Help Structure" in candidate.source_excerpt

    original_hash = candidate.source_hash
    help_component.write_text(
        "export function HelpPage() { return <main><h1>Changed Help Structure</h1></main> }",
        encoding="utf-8",
    )
    changed = CodePrototypeDiscoveryService().scan_project(project)[0]
    assert changed.source_hash != original_hash
    assert "Changed Help Structure" in changed.source_excerpt


def test_code_discovery_includes_referenced_i18n_copy(project: Project):
    repo = Path(project.repo_path)
    _write_page(
        repo,
        "frontend/src/app/help/page.tsx",
        (
            "import { HelpPage } from '@/features/help/HelpPage';\n"
            "export default function Page() { return <HelpPage /> }\n"
        ),
    )
    _write_page(
        repo,
        "frontend/src/features/help/HelpPage.tsx",
        (
            "import { useI18n } from '@/providers/I18nProvider';\n"
            "export function HelpPage() { const { t } = useI18n(); "
            "return <main>{t('help.quickStart')}</main> }"
        ),
    )
    zh = repo / "frontend/src/lib/i18n/zh-CN.ts"
    en = repo / "frontend/src/lib/i18n/en-US.ts"
    _write_page(
        repo,
        "frontend/src/lib/i18n/zh-CN.ts",
        'export const zh = {\n  "help.quickStart": "快速开始",\n};\n',
    )
    _write_page(
        repo,
        "frontend/src/lib/i18n/en-US.ts",
        'export const en = {\n  "help.quickStart": "Quick start",\n};\n',
    )

    candidate = CodePrototypeDiscoveryService().scan_project(project)[0]
    assert "frontend/src/lib/i18n/zh-CN.ts" in candidate.source_paths
    assert str(en.relative_to(repo)) in candidate.source_paths
    assert "frontend/src/lib/i18n/en-US.ts" in candidate.source_paths
    assert "快速开始" in candidate.source_excerpt
    assert "Quick start" in candidate.source_excerpt

    original_hash = candidate.source_hash
    zh.write_text(
        'export const zh = {\n  "help.quickStart": "新手引导",\n};\n',
        encoding="utf-8",
    )
    changed = CodePrototypeDiscoveryService().scan_project(project)[0]
    assert changed.source_hash != original_hash
    assert "新手引导" in changed.source_excerpt


async def _collect_code_batch(svc: PrototypeService, project_id: str):
    return [ev async for ev in svc.generate_all_from_code_stream(project_id)]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_code_generation_creates_then_skips_unchanged(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    _write_page(
        Path(project.repo_path),
        "frontend/src/app/page.tsx",
        "export default function HomePage() { return <main>Home</main> }",
    )

    first = await _collect_code_batch(svc, project.id)
    assert first[0].event == "scan_meta"
    assert first[-1].event == "all_done"
    assert first[-1].data["created"] == 1
    created = [ev for ev in first if ev.event == "prototype_done"]
    assert len(created) == 1

    listing = await svc.list_for_project(project.id)
    assert len(listing) == 1
    assert listing[0].source_kind == "code"
    assert listing[0].source_ref == "next-app-router--home"
    assert listing[0].current_version == 1

    second = await _collect_code_batch(svc, project.id)
    assert [ev.event for ev in second] == ["scan_meta", "candidate_start", "candidate_skip", "all_done"]
    assert second[-1].data["skipped"] == 1
    assert (await svc.get(listing[0].id)).current_version == 1


@pytest.mark.asyncio
@pytest.mark.slow
async def test_code_generation_changed_source_appends_new_version(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    repo = _project_repo_path(project)
    page = repo / "src/app/settings/page.tsx"
    _write_page(
        repo,
        "src/app/settings/page.tsx",
        "export default function SettingsPage() { return <main>One</main> }",
    )
    await _collect_code_batch(svc, project.id)
    proto = (await svc.list_for_project(project.id))[0]

    page.write_text(
        "export default function SettingsPage() { return <main>Two changed</main> }",
        encoding="utf-8",
    )
    second = await _collect_code_batch(svc, project.id)
    assert second[-1].data["regenerated"] == 1
    assert (await svc.get(proto.id)).current_version == 2


@pytest.mark.asyncio
@pytest.mark.slow
async def test_code_generation_failure_continues_with_remaining(
    svc: PrototypeService, project: Project, monkeypatch
):
    _write_page(Path(project.repo_path), "src/app/a/page.tsx", "export default function APage() { return <main>A</main> }")
    _write_page(Path(project.repo_path), "src/app/b/page.tsx", "export default function BPage() { return <main>B</main> }")
    calls = {"n": 0}

    async def conditional_stream(prompt, ctx):  # noqa: ARG001, RUF100
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("upstream 502")
            yield ""  # pragma: no cover
        async for chunk in _fake_stream_html_chunks(prompt, ctx):
            yield chunk

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        conditional_stream,
    )

    events = await _collect_code_batch(svc, project.id)
    assert events[-1].data["failed"] == 1
    assert events[-1].data["created"] == 1
    assert len([ev for ev in events if ev.event == "prototype_error"]) == 1
    assert len([ev for ev in events if ev.event == "prototype_done"]) == 1

    retry_preview = await svc.list_code_candidates(project.id)
    retry_actions = [
        action
        for item in _candidate_items(retry_preview)
        for action in [item.get("action")]
        if isinstance(action, str)
    ]
    assert sorted(retry_actions) == ["regenerate", "skip"]


@pytest.mark.asyncio
async def test_list_code_candidates_reports_actions(svc: PrototypeService, project: Project):
    _write_page(Path(project.repo_path), "src/app/page.tsx", "export default function HomePage() { return <main /> }")
    preview = await svc.list_code_candidates(project.id)
    assert preview["count"] == 1
    candidates = _candidate_items(preview)
    assert candidates[0]["action"] == "create"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_code_generation_can_target_selected_candidates_with_guidance(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    _write_page(Path(project.repo_path), "src/app/a/page.tsx", "export default function APage() { return <main>A</main> }")
    _write_page(Path(project.repo_path), "src/app/b/page.tsx", "export default function BPage() { return <main>B</main> }")

    events = [
        ev
        async for ev in svc.generate_all_from_code_stream(
            project.id,
            candidate_ids=["next-app-router--a"],
            instruction="Use a mobile-first operations layout.",
        )
    ]

    assert events[0].data["count"] == 1
    assert events[0].data["requested_count"] == 1
    assert events[-1].data["created"] == 1
    listing = await svc.list_for_project(project.id)
    assert len(listing) == 1
    assert listing[0].source_ref == "next-app-router--a"
    seed = await svc.store.load_prototype_version(listing[0].id, 0)
    assert seed is not None
    assert "Use a mobile-first operations layout." in (seed.instruction or "")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_code_generation_applies_candidate_specific_guidance(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    _write_page(Path(project.repo_path), "src/app/a/page.tsx", "export default function APage() { return <main>A</main> }")
    _write_page(Path(project.repo_path), "src/app/b/page.tsx", "export default function BPage() { return <main>B</main> }")

    events = [
        ev
        async for ev in svc.generate_all_from_code_stream(
            project.id,
            candidate_ids=["next-app-router--a", "next-app-router--b"],
            instruction="Use the console design language.",
            candidate_instructions={
                "next-app-router--a": "Make candidate A mobile-first.",
            },
        )
    ]

    assert events[-1].data["created"] == 2
    by_source = {p.source_ref: p for p in await svc.list_for_project(project.id)}
    seed_a = await svc.store.load_prototype_version(by_source["next-app-router--a"].id, 0)
    seed_b = await svc.store.load_prototype_version(by_source["next-app-router--b"].id, 0)
    assert seed_a is not None
    assert seed_b is not None
    assert "Shared guidance: Use the console design language." in (seed_a.instruction or "")
    assert "Candidate-specific guidance: Make candidate A mobile-first." in (
        seed_a.instruction or ""
    )
    assert "Shared guidance: Use the console design language." in (seed_b.instruction or "")
    assert "Candidate-specific guidance" not in (seed_b.instruction or "")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_code_generation_runtime_evidence_regenerates_unchanged_candidate(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    _write_page(
        Path(project.repo_path),
        "src/app/help/page.tsx",
        "export default function HelpPage() { return <main>Help from source</main> }",
    )

    first = [ev async for ev in svc.generate_all_from_code_stream(project.id)]
    assert first[-1].data["created"] == 1
    prototype = (await svc.list_for_project(project.id))[0]

    evidence = RuntimePrototypeEvidence(
        attempted_url="http://127.0.0.1:3000/help",
        final_url="http://127.0.0.1:3000/help",
        success=True,
        title="Runtime Help",
        visible_text_excerpt="Runtime Help\nLive search box",
        structure_summary="headings: Runtime Help; inputs: Search",
    )
    second = [
        ev
        async for ev in svc.generate_all_from_code_stream(
            project.id,
            candidate_ids=["next-app-router--help"],
            runtime_evidence_by_candidate={"next-app-router--help": evidence},
        )
    ]

    assert second[0].data["changed_count"] == 1
    assert second[-1].data["regenerated"] == 1
    seed = await svc.store.load_prototype_version(prototype.id, 0)
    assert seed is not None
    assert "Runtime browser evidence" in (seed.instruction or "")
    assert "Live search box" in (seed.instruction or "")
    updated = await svc.store.load_prototype(prototype.id)
    assert updated is not None
    assert "runtime_evidence" in (updated.source_meta_json or "")
    assert "Runtime Help" in (updated.source_meta_json or "")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_code_generation_can_capture_runtime_evidence_before_generation(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    _write_page(
        Path(project.repo_path),
        "src/app/issues/[id]/page.tsx",
        "export default function IssuePage() { return <main>Issue</main> }",
    )

    class _FakeCapture:
        async def capture_candidate(self, project, candidate, base_url):
            assert candidate.route == "/issues/:id"
            assert base_url == "http://localhost:4000"
            return RuntimePrototypeEvidence(
                attempted_url="http://localhost:4000/issues/demo-id",
                final_url="http://localhost:4000/issues/demo-id",
                success=True,
                title="Runtime Issue",
                visible_text_excerpt="Runtime Issue Detail",
                structure_summary="headings: Runtime Issue",
            )

    svc.runtime_capture_service = _FakeCapture()

    events = [
        ev
        async for ev in svc.generate_all_from_code_stream(
            project.id,
            use_runtime_evidence=True,
            runtime_base_url="http://localhost:4000",
        )
    ]

    assert "candidate_capture" in [ev.event for ev in events]
    assert "candidate_capture_done" in [ev.event for ev in events]
    assert events[-1].data["created"] == 1
    prototype = (await svc.list_for_project(project.id))[0]
    seed = await svc.store.load_prototype_version(prototype.id, 0)
    assert seed is not None
    assert "Runtime Issue Detail" in (seed.instruction or "")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_code_generation_capture_failure_falls_back_to_source_generation(
    svc: PrototypeService, project: Project, monkeypatch
):
    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        _fake_stream_html_chunks,
    )
    _write_page(
        Path(project.repo_path),
        "src/app/settings/page.tsx",
        "export default function SettingsPage() { return <main>Settings</main> }",
    )

    class _FakeCapture:
        async def capture_candidate(self, project, candidate, base_url):
            return RuntimePrototypeEvidence(
                attempted_url="http://localhost:4999/settings",
                success=False,
                failure_reason="connection refused",
            )

    svc.runtime_capture_service = _FakeCapture()

    events = [
        ev
        async for ev in svc.generate_all_from_code_stream(
            project.id,
            use_runtime_evidence=True,
            runtime_base_url="http://localhost:4999",
        )
    ]

    assert "candidate_capture_failed" in [ev.event for ev in events]
    assert events[-1].data["created"] == 1
    prototype = (await svc.list_for_project(project.id))[0]
    seed = await svc.store.load_prototype_version(prototype.id, 0)
    assert seed is not None
    assert "Capture status: failed or unavailable" in (seed.instruction or "")
