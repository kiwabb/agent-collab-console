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
from typing import AsyncIterator  # noqa: UP035

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.prototype_service import (
    PrototypeError,
    PrototypeService,
    StreamEvent,  # noqa: F401
    _stream_html,  # noqa: F401
    build_html_system_prompt,
    build_iteration_system_prompt,
    strip_markdown_fence,
)
from app.application.runtime_catalog_service import RuntimeCatalogService  # noqa: F401
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
