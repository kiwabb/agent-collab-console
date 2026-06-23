"""Prototype service tests.

We deliberately stay off the network — every test patches
`PrototypeService._stream_html` (the actual HTTP SSE parser) with an
async generator that yields a fixed chunk sequence, so the service-level
prompt assembly, version bookkeeping, code-fence stripping, and disk
mirror are exercised without needing a live LLM endpoint.

Disk-touching tests are tagged `@pytest.mark.slow` per the PRD, so the
default `pytest -v` run stays fast.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import AsyncIterator

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.prototype_service import (
    PrototypeError,
    PrototypeService,
    StreamEvent,
    _stream_html,
    build_html_system_prompt,
    build_iteration_system_prompt,
    strip_markdown_fence,
)
from app.application.runtime_catalog_service import RuntimeCatalogService
from app.domain.models import Project, RuntimeExecutorConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path: Path) -> AsyncSQLiteStore:
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


def _make_git_repo(path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True)
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
    assert strip_markdown_fence(
        "```html\n<!DOCTYPE html>\n<html></html>\n```"
    ) == "<!DOCTYPE html>\n<html></html>"
    assert strip_markdown_fence("```HTML\n<body></body>\n```") == "<body></body>"
    # Already-clean HTML stays untouched.
    raw = "<!DOCTYPE html>\n<html></html>"
    assert strip_markdown_fence(raw) == raw
    # Truncated ```html with no closing fence -> stripped leading fence line.
    truncated = "```html\n<!DOCTYPE html>\n<html></html>"
    assert strip_markdown_fence(truncated).startswith("<!DOCTYPE html>")


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


async def _fake_stream_html_chunks(
    prompt: str, ctx
) -> AsyncIterator[str]:  # noqa: ARG001
    # Mirror what a real LLM would do: start with <!DOCTYPE html>, end with
    # </html>. We DO include a stray markdown fence to exercise strip_markdown_fence.
    yield "```html\n"
    yield "<!DOCTYPE html>\n"
    yield "<html><body><h1>Pricing</h1>"
    yield "<p>three cards</p></body></html>\n"
    yield "```\n"


async def _collect(svc: PrototypeService, prototype_id: str, instruction: str | None):
    return [
        ev
        async for ev in svc.stream_events(prototype_id, instruction)
    ]


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

    async def fake_iter(prompt, ctx):  # noqa: ARG001
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
    assert [v.version_no for v in detail["versions"]] == [1, 2]
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
    async def empty_stream(prompt, ctx):  # noqa: ARG001
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
async def test_stream_aborts_on_runtime_error(
    svc: PrototypeService, project: Project, monkeypatch
):
    async def boom(prompt, ctx):  # noqa: ARG001
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