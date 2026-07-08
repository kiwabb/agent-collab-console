"""FastAPI integration test for the /api/codex/version endpoint."""
from datetime import datetime


def test_codex_version_returns_ok(client):
    """GET /api/codex/version returns version 0.1.0 and started_at in ISO8601 format."""
    resp = client.get("/api/codex/version")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/json")
    body = resp.json()
    assert body["version"] == "0.1.0"
    assert "started_at" in body
    dt = datetime.fromisoformat(body["started_at"])
    assert dt.tzinfo is not None, "started_at must include timezone info"


def test_codex_version_started_at_consistent(client):
    """Multiple calls to /api/codex/version return the same started_at value."""
    resp1 = client.get("/api/codex/version")
    resp2 = client.get("/api/codex/version")
    assert resp1.json()["started_at"] == resp2.json()["started_at"]
