"""FastAPI tests for the Codex ready endpoint."""


def test_codex_ready_returns_ok(client):
    resp = client.get("/api/codex/ready")

    assert resp.status_code == 200
    assert resp.json() == {"ready": True}
