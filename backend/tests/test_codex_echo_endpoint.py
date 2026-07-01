"""FastAPI tests for the Codex echo endpoint."""


def test_codex_echo_normal_message(client):
    resp = client.get("/api/codex/echo?msg=hello")
    assert resp.status_code == 200
    data = resp.json()
    assert data["msg"] == "hello"
    assert data["length"] == 5
    assert "ts" in data


def test_codex_echo_empty_string(client):
    resp = client.get("/api/codex/echo?msg=")
    assert resp.status_code == 200
    data = resp.json()
    assert data["msg"] == ""
    assert data["length"] == 0
    assert "ts" in data


def test_codex_echo_default_empty(client):
    resp = client.get("/api/codex/echo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["msg"] == ""
    assert data["length"] == 0
    assert "ts" in data


def test_codex_echo_unicode(client):
    resp = client.get("/api/codex/echo?msg=你好世界")
    assert resp.status_code == 200
    data = resp.json()
    assert data["msg"] == "你好世界"
    assert data["length"] == 4
    assert "ts" in data


def test_codex_echo_very_long_string(client):
    long_msg = "a" * 2000
    resp = client.get(f"/api/codex/echo?msg={long_msg}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["msg"] == long_msg
    assert data["length"] == 2000
    assert "ts" in data
