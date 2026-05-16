"""FastAPI integration test for the /api/browser-smoke endpoint."""
import pytest


def test_browser_smoke_returns_ok_true(client):
    """GET /api/browser-smoke returns { ok: true } with HTTP 200."""
    resp = client.get("/api/browser-smoke")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/json")
    body = resp.json()
    assert body == {"ok": True}