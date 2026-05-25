"""FastAPI tests for the Codex heartbeat endpoint."""


def test_codex_heartbeat_returns_ok(client):
    resp = client.get("/api/codex/heartbeat")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
