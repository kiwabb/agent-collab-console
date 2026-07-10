"""Prototype API endpoint tests.

CRUD + the SSE `/stream` endpoint. The SSE test monkeypatches
`PrototypeService._stream_html` to drive the prompt assembly + version
bookkeeping + DB + disk mirror pipeline without hitting a real LLM.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.domain.models import Project


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


def test_code_scan_routes_are_removed(client, seeded_project):
    pid = seeded_project
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/projects/{project_id}/prototypes/code-candidates" not in paths
    assert "/api/projects/{project_id}/prototypes/generate-from-code/stream" not in paths
    assert client.get(f"/api/projects/{pid}/prototypes/code-candidates").status_code == 404
    assert (
        client.get(f"/api/projects/{pid}/prototypes/generate-from-code/stream").status_code
        == 404
    )
