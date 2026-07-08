from __future__ import annotations

import json


def test_runtime_catalog_api_masks_and_preserves_api_keys(client):
    secret = "runtime-secret-should-not-leak"
    response = client.put(
        "/api/runtime-catalog",
        json={
            "catalog": {
                "executors": [
                    {
                        "id": "codex-openai",
                        "label": "Codex OpenAI",
                        "enabled": True,
                        "executor_type": "codex",
                        "api_endpoint": "http://127.0.0.1:8317/v1",
                        "api_key": secret,
                        "default_model": "gpt-5.5",
                        "protocol": "openai",
                        "providers": [],
                        "default_provider_id": None,
                    }
                ]
            }
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert secret not in json.dumps(body)
    assert "api_key" not in body["executors"][0]
    assert body["executors"][0]["api_key_configured"] is True

    edited = body
    edited["executors"][0]["label"] = "Codex OpenAI Updated"
    edited["executors"][0].pop("api_key", None)
    response = client.put("/api/runtime-catalog", json={"catalog": edited})

    assert response.status_code == 200, response.text
    assert response.json()["executors"][0]["api_key_configured"] is True

    import app.bootstrap as bootstrap_module

    assert bootstrap_module.store is not None
    stored = bootstrap_module.store.load_runtime_catalog()
    assert stored is not None
    assert stored.executors[0].api_key == secret


def test_runtime_catalog_test_uses_openai_protocol_and_v1_base_url(client, monkeypatch):
    response = client.put(
        "/api/runtime-catalog",
        json={
            "catalog": {
                "executors": [
                    {
                        "id": "codex-openai",
                        "label": "Codex OpenAI",
                        "enabled": True,
                        "executor_type": "codex",
                        "api_endpoint": "http://127.0.0.1:8317/v1",
                        "api_key": "secret-value",
                        "default_model": "gpt-5.5",
                        "protocol": "openai",
                        "providers": [],
                        "default_provider_id": None,
                    }
                ]
            }
        },
    )
    assert response.status_code == 200, response.text

    calls = []

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    response = client.post(
        "/api/runtime-catalog/test",
        json={"executor_id": "codex-openai", "model_id": "gpt-5.5"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert calls == [
        {
            "url": "http://127.0.0.1:8317/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer secret-value",
                "content-type": "application/json",
            },
            "json": {
                "model": "gpt-5.5",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
            "timeout": 120.0,
        }
    ]


def test_runtime_catalog_test_uses_effective_config_with_custom_endpoint(
    client, monkeypatch
):
    response = client.put(
        "/api/runtime-catalog",
        json={
            "catalog": {
                "executors": [
                    {
                        "id": "claude-minimax",
                        "label": "Claude MiniMax",
                        "enabled": True,
                        "executor_type": "claude",
                        "api_endpoint": "http://127.0.0.1:8318",
                        "api_key": "secret-value",
                        "default_model": "MiniMax-M3",
                        "protocol": "anthropic",
                        "default_provider_id": "anthropic",
                        "providers": [
                            {
                                "id": "anthropic",
                                "label": "Anthropic",
                                "enabled": True,
                                "default_model_id": "claude-sonnet-4-6",
                                "models": [
                                    {
                                        "id": "claude-sonnet-4-6",
                                        "label": "Claude Sonnet 4.6",
                                        "enabled": True,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    )
    assert response.status_code == 200, response.text

    calls = []

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    response = client.post(
        "/api/runtime-catalog/test",
        json={"executor_id": "claude-minimax"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert calls == [
        {
            "url": "http://127.0.0.1:8318/v1/messages",
            "headers": {
                "x-api-key": "secret-value",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            "json": {
                "model": "MiniMax-M3",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
            "timeout": 120.0,
        }
    ]


def test_runtime_catalog_test_treats_http_200_error_body_as_failure(
    client, monkeypatch
):
    response = client.put(
        "/api/runtime-catalog",
        json={
            "catalog": {
                "executors": [
                    {
                        "id": "claude-minimax",
                        "label": "Claude MiniMax",
                        "enabled": True,
                        "executor_type": "claude",
                        "api_endpoint": "http://127.0.0.1:8318",
                        "api_key": "bad-secret",
                        "default_model": "MiniMax-M3",
                        "protocol": "anthropic",
                        "providers": [],
                        "default_provider_id": None,
                    }
                ]
            }
        },
    )
    assert response.status_code == 200, response.text

    class FakeResponse:
        status_code = 200
        text = '{"error_status":401,"error_msg":"无效的令牌"}'

        def json(self):
            return {"error_status": 401, "error_msg": "无效的令牌"}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    response = client.post(
        "/api/runtime-catalog/test",
        json={"executor_id": "claude-minimax"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"success": False, "error": "API error 401: 无效的令牌"}
