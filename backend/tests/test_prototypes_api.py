"""Prototype API endpoint tests.

CRUD + the SSE `/stream` endpoint. The SSE test monkeypatches
`PrototypeService._stream_html` to drive the prompt assembly + version
bookkeeping + DB + disk mirror pipeline without hitting a real LLM.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import AsyncIterator  # noqa: F401, UP035

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore  # noqa: F401
from app.application.prototype_service import PrototypeService  # noqa: F401
from app.domain.models import Project, RuntimeExecutorConfig  # noqa: F401
from app.interfaces.sse import MAX_CANDIDATE_QUERY_TEXT_CHARS, _parse_runtime_evidence


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
async def seeded_project(tmp_path: Path):
    """Stand up a Project row in the live test store, then return its id."""
    import app.bootstrap as bootstrap_module  # noqa: I001
    from datetime import datetime

    repo = _make_git_repo(tmp_path / "demo")
    store = bootstrap_module.async_store
    assert store is not None
    project = Project(
        id=f"proj-test-{tmp_path.name}",
        name="demo",
        repo_path=str(repo),
        default_branch="main",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await store.save_project(project)
    yield project.id


def _patch_stream(monkeypatch):
    """Wire PrototypeService._stream_html to a fixed-shape fake."""

    async def fake_stream(prompt, ctx):  # noqa: ARG001, RUF100
        yield "```html\n"
        yield "<!DOCTYPE html>\n"
        yield "<html><body><h1>Pricing</h1>"
        yield "<p>cards</p></body></html>\n"
        yield "```\n"

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        fake_stream,
    )

    # The test store has no runtime executor configured, so
    # resolve_streaming_context returns None — short-circuit with a fake ctx
    # so the SSE endpoint can drive the meta event + the prompt flow.
    from app.application.llm_runner import StreamingPlanContext

    def fake_ctx(catalog):  # noqa: ARG001, RUF100
        return StreamingPlanContext(
            executor_id="claude",
            executor_label="claude",
            model="claude-test-model",
            endpoint="https://example.invalid",
            api_key="sk-test",
            max_tokens=8192,
            timeout_s=28.0,
        )

    monkeypatch.setattr(
        "app.application.prototype_service.resolve_streaming_context",
        fake_ctx,
    )


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


def test_create_then_list_prototypes(client, seeded_project):
    pid = seeded_project
    resp = client.post(
        f"/api/projects/{pid}/prototypes",
        json={"title": "Pricing", "brief": "Three-card SaaS pricing"},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["title"] == "Pricing"
    assert created["current_version"] == 0
    assert created["framework"] == "html"

    listing = client.get(f"/api/projects/{pid}/prototypes")
    assert listing.status_code == 200
    items = listing.json()
    assert any(it["id"] == created["id"] for it in items)


def test_create_rejects_missing_project(client):
    resp = client.post(
        "/api/projects/no-such/prototyles".replace("prototyles", "prototypes"),
        json={"title": "X", "brief": "Y"},
    )
    assert resp.status_code == 404


def test_create_rejects_empty_brief(client, seeded_project):
    resp = client.post(
        f"/api/projects/{seeded_project}/prototypes",
        json={"title": "X", "brief": "   "},
    )
    assert resp.status_code == 400


def test_parse_runtime_evidence_ignores_non_object_json_payloads():
    evidence = _parse_runtime_evidence(
        [
            'candidate-a\t{"success":true,"title":"Loaded"}',
            'candidate-b\t[]',
            'candidate-c\t"bad"',
            "candidate-d\t{bad",
        ]
    )

    assert list(evidence.keys()) == ["candidate-a"]
    assert evidence["candidate-a"].success is True
    assert evidence["candidate-a"].title == "Loaded"


def test_get_prototype_hides_seed_v0(client, seeded_project):
    pid = seeded_project
    created = client.post(
        f"/api/projects/{pid}/prototypes",
        json={"title": "P", "brief": "b"},
    ).json()
    detail = client.get(f"/api/prototypes/{created['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["prototype"]["id"] == created["id"]
    # Seed v0 must NOT leak into the version list.
    assert body["versions"] == []


def test_delete_prototype_returns_404_after(client, seeded_project):
    pid = seeded_project
    created = client.post(
        f"/api/projects/{pid}/prototypes",
        json={"title": "P", "brief": "b"},
    ).json()
    proto_id = created["id"]
    assert client.delete(f"/api/prototypes/{proto_id}").status_code == 200
    assert client.get(f"/api/prototypes/{proto_id}").status_code == 404


# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------


def _consume_sse(response) -> list[dict]:
    """Parse a `text/event-stream` response into a list of {event, data}.

    The TestClient streams synchronously into response.text, so we can
    split on the `\\n\\n` event boundary and JSON-decode each data line.
    """
    raw = response.text
    events: list[dict] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev_type = None
        ev_data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                import json as _json

                ev_data = _json.loads(line.split(":", 1)[1].strip())
        if ev_type and ev_data is not None:
            events.append({"event": ev_type, "data": ev_data})
    return events


def test_stream_generates_v1_with_meta_delta_done(client, seeded_project, monkeypatch):
    _patch_stream(monkeypatch)
    pid = seeded_project
    created = client.post(
        f"/api/projects/{pid}/prototypes",
        json={"title": "P", "brief": "SaaS pricing"},
    ).json()

    with client.stream("GET", f"/api/prototypes/{created['id']}/stream") as response:
        # FastAPI returns 200 + text/event-stream; collect the body.
        from starlette.responses import StreamingResponse as _SSR  # noqa: F401

        body = b"".join(response.iter_bytes())
        # Re-shape into the same event list as the sync helper.
        text = body.decode("utf-8")
    events = _consume_sse_response(text)
    if events and events[0]["event"] == "error":
        pytest.fail(f"SSE returned error event: body={text[:1000]!r} events={events!r}")
    types = [e["event"] for e in events]
    assert types[0] == "meta"
    assert "delta" in types
    assert types[-1] == "done"
    done = events[-1]["data"]
    assert done["version_no"] == 1
    assert done["html"].lstrip().startswith("<!DOCTYPE html>")
    assert done["html"].rstrip().endswith("</html>")
    assert "```" not in done["html"]
    assert done["disk_path"] is not None


def test_stream_with_instruction_iterates_to_v2(client, seeded_project, monkeypatch):
    _patch_stream(monkeypatch)
    pid = seeded_project
    created = client.post(
        f"/api/projects/{pid}/prototypes",
        json={"title": "P", "brief": "SaaS pricing"},
    ).json()
    pid_proto = created["id"]

    # v1
    with client.stream("GET", f"/api/prototypes/{pid_proto}/stream") as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    assert _consume_sse_response(text)[-1]["data"]["version_no"] == 1

    # v2 via ?instruction=
    with client.stream(
        "GET", f"/api/prototypes/{pid_proto}/stream?instruction=make+it+bolder"
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[-1]["data"]["version_no"] == 2

    detail = client.get(f"/api/prototypes/{pid_proto}").json()
    assert [v["version_no"] for v in detail["versions"]] == [1, 2]


def test_stream_returns_404_for_unknown_prototype(client):
    resp = client.get("/api/prototypes/nope/stream")
    assert resp.status_code == 404


def test_version_html_endpoint_returns_body(client, seeded_project, monkeypatch):
    _patch_stream(monkeypatch)
    pid = seeded_project
    created = client.post(
        f"/api/projects/{pid}/prototypes",
        json={"title": "P", "brief": "b"},
    ).json()
    pid_proto = created["id"]
    with client.stream("GET", f"/api/prototypes/{pid_proto}/stream") as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    done = events[-1]["data"]
    fetched = client.get(f"/api/prototypes/{pid_proto}/versions/1")
    assert fetched.status_code == 200
    assert fetched.json()["html"] == done["html"]


def _consume_sse_response(text: str) -> list[dict]:
    events: list[dict] = []
    import json as _json

    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev_type = None
        ev_data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                ev_data = _json.loads(line.split(":", 1)[1].strip())
        if ev_type and ev_data is not None:
            events.append({"event": ev_type, "data": ev_data})
    return events


# ---------------------------------------------------------------------------
# Batch regenerate-all endpoint
# ---------------------------------------------------------------------------


def test_regenerate_all_stream_emits_batch_envelope_and_per_prototype_done(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    c1 = client.post(
        f"/api/projects/{pid}/prototypes",
        json={"title": "A", "brief": "brief a"},
    ).json()
    c2 = client.post(
        f"/api/projects/{pid}/prototypes",
        json={"title": "B", "brief": "brief b"},
    ).json()

    with client.stream("GET", f"/api/projects/{pid}/prototypes/regenerate-all/stream") as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    types = [e["event"] for e in events]

    assert types[0] == "batch_meta"
    assert events[0]["data"] == {"count": 2}
    assert types[-1] == "all_done"

    starts = [e for e in events if e["event"] == "prototype_start"]
    assert {e["data"]["prototype_id"] for e in starts} == {c1["id"], c2["id"]}

    dones = [e for e in events if e["event"] == "prototype_done"]
    assert {e["data"]["prototype_id"] for e in dones} == {c1["id"], c2["id"]}
    for e in dones:
        assert e["data"]["version_no"] == 1

    # The ok list follows list_for_project's updated_at-DESC ordering, which
    # is unstable for ties within the same second — compare as sets.
    summary = events[-1]["data"]
    assert sorted(summary["ok"]) == sorted([c1["id"], c2["id"]])
    assert summary["failed"] == []


def test_regenerate_all_stream_returns_404_for_unknown_project(client):
    resp = client.get("/api/projects/no-such-project/prototypes/regenerate-all/stream")
    assert resp.status_code == 404


def test_regenerate_all_stream_with_no_prototypes_emits_zero_summary(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    with client.stream("GET", f"/api/projects/{pid}/prototypes/regenerate-all/stream") as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert [e["event"] for e in events] == ["batch_meta", "all_done"]
    assert events[0]["data"] == {"count": 0}
    assert events[-1]["data"] == {"ok": [], "failed": []}


# ---------------------------------------------------------------------------
# Code-driven endpoints
# ---------------------------------------------------------------------------


def _write_page_for_api(project_id: str, rel: str, body: str) -> None:
    import sqlite3

    import app.bootstrap as bootstrap_module

    store = bootstrap_module.async_store
    assert store is not None
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute("SELECT repo_path FROM projects WHERE id = ?", (project_id,)).fetchone()
    assert row is not None
    path = Path(row[0]) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_code_candidates_endpoint_returns_preview(client, seeded_project):
    pid = seeded_project
    _write_page_for_api(
        pid,
        "frontend/src/app/projects/[id]/prototypes/page.tsx",
        "export default function ProjectPrototypesPage() { return <main /> }",
    )
    resp = client.get(f"/api/projects/{pid}/prototypes/code-candidates")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    candidate = body["candidates"][0]
    assert candidate["route"] == "/projects/:id/prototypes"
    assert candidate["action"] == "create"


def test_generate_from_code_stream_creates_then_skips(client, seeded_project, monkeypatch):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/page.tsx",
        "export default function HomePage() { return <main>Home</main> }",
    )

    with client.stream("GET", f"/api/projects/{pid}/prototypes/generate-from-code/stream") as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[0]["event"] == "scan_meta"
    assert events[-1]["event"] == "all_done"
    assert events[-1]["data"]["created"] == 1
    assert len([e for e in events if e["event"] == "prototype_done"]) == 1

    with client.stream("GET", f"/api/projects/{pid}/prototypes/generate-from-code/stream") as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    second = _consume_sse_response(text)
    assert [e["event"] for e in second] == ["scan_meta", "candidate_start", "candidate_skip", "all_done"]
    assert second[-1]["data"]["skipped"] == 1


def test_generate_from_code_stream_returns_404_for_unknown_project(client):
    resp = client.get("/api/projects/no-such-project/prototypes/generate-from-code/stream")
    assert resp.status_code == 404


def test_generate_from_code_stream_accepts_selected_candidate_and_instruction(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/a/page.tsx",
        "export default function APage() { return <main>A</main> }",
    )
    _write_page_for_api(
        pid,
        "src/app/b/page.tsx",
        "export default function BPage() { return <main>B</main> }",
    )

    with client.stream(
        "GET",
        (
            f"/api/projects/{pid}/prototypes/generate-from-code/stream"
            "?candidate_id=next-app-router--a&instruction=mobile-first"
        ),
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[0]["data"]["count"] == 1
    assert events[0]["data"]["requested_count"] == 1
    assert events[-1]["data"]["created"] == 1


def test_generate_from_code_stream_accepts_candidate_specific_instruction(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/a/page.tsx",
        "export default function APage() { return <main>A</main> }",
    )

    with client.stream(
        "GET",
        (
            f"/api/projects/{pid}/prototypes/generate-from-code/stream"
            "?candidate_id=next-app-router--a"
            "&candidate_instruction=next-app-router--a%09emphasize%20error%20states"
        ),
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[0]["data"]["requested_count"] == 1
    assert events[-1]["data"]["created"] == 1


def test_generate_from_code_stream_accepts_candidate_brief_override(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/a/page.tsx",
        "export default function APage() { return <main>A</main> }",
    )

    seen: dict[str, str] = {}

    async def capture_prompt(prompt, ctx):
        seen["prompt"] = prompt
        yield "<!DOCTYPE html><html><body><h1>Override</h1></body></html>"

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        capture_prompt,
    )

    with client.stream(
        "GET",
        (
            f"/api/projects/{pid}/prototypes/generate-from-code/stream"
            "?candidate_id=next-app-router--a"
            "&candidate_brief_override=next-app-router--a%09Focus%20on%20custom%20queue"
        ),
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[0]["data"]["requested_count"] == 1
    assert events[-1]["data"]["created"] == 1
    assert "User-edited candidate brief override" in seen["prompt"]
    assert "custom queue" in seen["prompt"]


def test_generate_from_code_stream_trims_candidate_brief_override(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/a/page.tsx",
        "export default function APage() { return <main>A</main> }",
    )

    from urllib.parse import quote

    seen: dict[str, str] = {}
    long_override = "x" * 1300

    async def capture_prompt(prompt, ctx):
        seen["prompt"] = prompt
        yield "<!DOCTYPE html><html><body><h1>Trimmed</h1></body></html>"

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        capture_prompt,
    )

    encoded_override = quote(f"next-app-router--a\t{long_override}")
    with client.stream(
        "GET",
        (
            f"/api/projects/{pid}/prototypes/generate-from-code/stream"
            "?candidate_id=next-app-router--a"
            f"&candidate_brief_override={encoded_override}"
        ),
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[-1]["data"]["created"] == 1
    assert "x" * MAX_CANDIDATE_QUERY_TEXT_CHARS in seen["prompt"]
    assert "x" * (MAX_CANDIDATE_QUERY_TEXT_CHARS + 1) not in seen["prompt"]


def test_generate_from_code_stream_ignores_blank_candidate_brief_override(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/a/page.tsx",
        "export default function APage() { return <main>A</main> }",
    )

    from urllib.parse import quote

    seen: dict[str, str] = {}

    async def capture_prompt(prompt, ctx):
        seen["prompt"] = prompt
        yield "<!DOCTYPE html><html><body><h1>No blank override</h1></body></html>"

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        capture_prompt,
    )

    encoded_override = quote("next-app-router--a\t   ")
    with client.stream(
        "GET",
        (
            f"/api/projects/{pid}/prototypes/generate-from-code/stream"
            "?candidate_id=next-app-router--a"
            f"&candidate_brief_override={encoded_override}"
        ),
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[-1]["data"]["created"] == 1
    assert "User-edited candidate brief override" not in seen["prompt"]


def test_generate_from_code_stream_trims_candidate_instruction(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/a/page.tsx",
        "export default function APage() { return <main>A</main> }",
    )

    from urllib.parse import quote

    seen: dict[str, str] = {}
    long_instruction = "y" * 1300

    async def capture_prompt(prompt, ctx):
        seen["prompt"] = prompt
        yield "<!DOCTYPE html><html><body><h1>Trimmed instruction</h1></body></html>"

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        capture_prompt,
    )

    encoded_instruction = quote(f"next-app-router--a\t{long_instruction}")
    with client.stream(
        "GET",
        (
            f"/api/projects/{pid}/prototypes/generate-from-code/stream"
            "?candidate_id=next-app-router--a"
            f"&candidate_instruction={encoded_instruction}"
        ),
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[-1]["data"]["created"] == 1
    assert "y" * MAX_CANDIDATE_QUERY_TEXT_CHARS in seen["prompt"]
    assert "y" * (MAX_CANDIDATE_QUERY_TEXT_CHARS + 1) not in seen["prompt"]


def test_generate_from_code_stream_ignores_blank_candidate_instruction(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/a/page.tsx",
        "export default function APage() { return <main>A</main> }",
    )

    from urllib.parse import quote

    seen: dict[str, str] = {}

    async def capture_prompt(prompt, ctx):
        seen["prompt"] = prompt
        yield "<!DOCTYPE html><html><body><h1>No blank instruction</h1></body></html>"

    monkeypatch.setattr(
        "app.application.prototype_service._stream_html",
        capture_prompt,
    )

    encoded_instruction = quote("next-app-router--a\t   ")
    with client.stream(
        "GET",
        (
            f"/api/projects/{pid}/prototypes/generate-from-code/stream"
            "?candidate_id=next-app-router--a"
            f"&candidate_instruction={encoded_instruction}"
        ),
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")
    events = _consume_sse_response(text)
    assert events[-1]["data"]["created"] == 1
    assert "Additional user guidance for this selected generation run" not in seen["prompt"]


def test_generate_from_code_stream_accepts_runtime_evidence_and_ignores_malformed(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/help/page.tsx",
        "export default function HelpPage() { return <main>Help</main> }",
    )

    import json as _json
    from urllib.parse import quote

    evidence = quote(
        "next-app-router--help\t"
        + _json.dumps(
            {
                "attempted_url": "http://127.0.0.1:3000/help",
                "final_url": "http://127.0.0.1:3000/help",
                "success": True,
                "title": "Runtime Help",
                "visible_text_excerpt": "Runtime Help\nLive docs",
                "structure_summary": "headings: Runtime Help; buttons: Search",
                "cookies": "must-not-pass-through",
            }
        )
    )

    with client.stream(
        "GET",
        (
            f"/api/projects/{pid}/prototypes/generate-from-code/stream"
            f"?candidate_id=next-app-router--help&runtime_evidence=not-json"
            f"&runtime_evidence={evidence}"
        ),
    ) as response:
        text = b"".join(response.iter_bytes()).decode("utf-8")

    events = _consume_sse_response(text)
    assert events[0]["data"]["requested_count"] == 1
    assert events[-1]["data"]["created"] == 1

    listing = client.get(f"/api/projects/{pid}/prototypes")
    assert listing.status_code == 200
    source_meta = listing.json()[0]["source_meta_json"]
    assert "Runtime Help" in source_meta
    assert "must-not-pass-through" not in source_meta


def test_generate_from_code_stream_can_request_runtime_capture(
    client, seeded_project, monkeypatch
):
    _patch_stream(monkeypatch)
    pid = seeded_project
    _write_page_for_api(
        pid,
        "src/app/issues/[id]/page.tsx",
        "export default function IssuePage() { return <main>Issue</main> }",
    )

    import app.bootstrap as bootstrap_module
    from app.application.prototype_service import RuntimePrototypeEvidence

    assert bootstrap_module.prototype_service is not None
    original_capture_service = bootstrap_module.prototype_service.runtime_capture_service

    class _FakeCapture:
        async def capture_candidate(self, project, candidate, base_url):
            return RuntimePrototypeEvidence(
                attempted_url="http://localhost:4000/issues/demo-id",
                final_url="http://localhost:4000/issues/demo-id",
                success=True,
                title="Runtime Issue",
                visible_text_excerpt="Runtime Issue Detail",
                structure_summary="headings: Runtime Issue",
            )

    bootstrap_module.prototype_service.runtime_capture_service = _FakeCapture()
    try:
        with client.stream(
            "GET",
            (
                f"/api/projects/{pid}/prototypes/generate-from-code/stream"
                "?candidate_id=next-app-router--issues-id"
                "&use_runtime_evidence=true"
                "&runtime_base_url=http%3A%2F%2Flocalhost%3A4000"
            ),
        ) as response:
            text = b"".join(response.iter_bytes()).decode("utf-8")
    finally:
        bootstrap_module.prototype_service.runtime_capture_service = original_capture_service

    events = _consume_sse_response(text)
    assert "candidate_capture" in [event["event"] for event in events]
    assert "candidate_capture_done" in [event["event"] for event in events]
    assert events[-1]["data"]["created"] == 1
