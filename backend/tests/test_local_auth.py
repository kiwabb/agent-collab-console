from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.application.local_auth import LocalAuthConfigError, load_local_auth_config
from app.main import app


def _authorized_headers(**overrides: str) -> dict[str, str]:
    headers = {
        "X-Console-Token": os.environ["CONSOLE_AUTH_TOKEN"],
        "Origin": "http://testserver",
    }
    for key, value in overrides.items():
        existing = next((name for name in headers if name.lower() == key.lower()), None)
        if existing is not None:
            del headers[existing]
        headers[key] = value
    return headers


def test_health_is_the_only_anonymous_http_endpoint() -> None:
    client = TestClient(app)

    assert client.get("/api/health").status_code == 200
    response = client.get("/api/browser-smoke")

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_console_token"}


def test_protected_http_rejects_wrong_token_and_accepts_header_or_cookie() -> None:
    client = TestClient(app)

    wrong = client.get(
        "/api/browser-smoke",
        headers={"X-Console-Token": "wrong", "Origin": "http://testserver"},
    )
    assert wrong.status_code == 401

    valid_header = client.get("/api/browser-smoke", headers=_authorized_headers())
    assert valid_header.status_code == 200

    client.cookies.set("console_auth_token", os.environ["CONSOLE_AUTH_TOKEN"])
    valid_cookie = client.get(
        "/api/browser-smoke",
        headers={"Origin": "http://testserver"},
    )
    assert valid_cookie.status_code == 200


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        ({"host": "console.attacker.test"}, "host_not_allowed"),
        ({"origin": "https://attacker.test"}, "origin_not_allowed"),
    ],
)
def test_http_rejects_untrusted_host_or_origin(headers: dict[str, str], reason: str) -> None:
    client = TestClient(app)

    response = client.get(
        "/api/browser-smoke",
        headers=_authorized_headers(**headers),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": reason}


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://testserver"},
        _authorized_headers(Origin="https://attacker.test"),
    ],
)
def test_websocket_rejects_before_accept(headers: dict[str, str]) -> None:
    client = TestClient(app)

    with (
        pytest.raises(WebSocketDisconnect) as caught,
        client.websocket_connect("/api/ws/events", headers=headers),
    ):
        pass

    assert caught.value.code == 1008


def test_missing_or_short_console_token_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSOLE_AUTH_TOKEN", "short")

    with pytest.raises(LocalAuthConfigError, match="at least 32"):
        load_local_auth_config()


def test_non_loopback_host_or_origin_cannot_be_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONSOLE_ALLOWED_HOSTS", "example.com")
    with pytest.raises(LocalAuthConfigError, match="only loopback"):
        load_local_auth_config()

    monkeypatch.setenv("CONSOLE_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("CONSOLE_ALLOWED_ORIGINS", "https://example.com")
    with pytest.raises(LocalAuthConfigError, match="only loopback HTTP origins"):
        load_local_auth_config()
