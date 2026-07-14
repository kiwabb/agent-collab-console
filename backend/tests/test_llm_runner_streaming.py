from __future__ import annotations

from typing import cast

import pytest

import app.application.llm_runner as llm_runner_module
from app.application.llm_runner import (
    LLMOutputTokenLimitError,
    StreamingPlanContext,
    build_llm_runner,
    call_llm_with_tools_streaming,
    stream_llm,
)
from app.application.runtime_catalog_service import RuntimeCatalogService
from app.domain.models import RuntimeCatalog, RuntimeExecutorConfig


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers=None, json=None):  # noqa: ANN001, RUF100
        lines = [
            'data: {"type":"message_start","message":{"usage":{"input_tokens":12}}}',
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hel"}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"lo"}}',
            'data: {"type":"content_block_stop","index":0}',
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"dispatch_subagent"}}',
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"role\\":\\"engineer\\"}"}}',
            'data: {"type":"content_block_stop","index":1}',
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":7}}',
            'data: {"type":"message_stop"}',
        ]
        return _FakeStreamResponse(lines)


class _NoisyStreamClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers=None, json=None):  # noqa: ANN001, RUF100
        return _FakeStreamResponse(
            [
                "data: []",
                "data: not json",
                'data: {"type":"content_block_delta","delta":"bad"}',
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
                'data: {"type":"message_stop"}',
            ]
        )


class _CatalogService:
    async def load_catalog(self) -> RuntimeCatalog:
        return RuntimeCatalog(
            executors=[
                RuntimeExecutorConfig(
                    id="minimax",
                    label="MiniMax",
                    api_endpoint="https://example.test",
                    api_key="secret",
                    default_model="MiniMax-M3",
                )
            ]
        )


class _JsonResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def json(self) -> object:
        return self.payload


class _PrefillRetryClient:
    payloads: list[dict[str, object]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):  # noqa: ANN001, RUF100
        assert isinstance(json, dict)
        self.payloads.append(json)
        if len(self.payloads) == 1:
            return _JsonResponse({"content": None, "stop_reason": "end_turn"})
        return _JsonResponse(
            {
                "content": [{"type": "text", "text": '{"items":[]}'}],
                "stop_reason": "end_turn",
            }
        )


class _MaxTokenClient:
    payloads: list[dict[str, object]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):  # noqa: ANN001, RUF100
        assert isinstance(json, dict)
        self.payloads.append(json)
        return _JsonResponse(
            {
                "content": [{"type": "text", "text": '{"items":['}],
                "stop_reason": "max_tokens",
            }
        )


@pytest.mark.asyncio
async def test_call_llm_with_tools_streaming_reconstructs_message_and_batches(monkeypatch):
    monkeypatch.setattr(llm_runner_module.httpx, "AsyncClient", _FakeAsyncClient)
    deltas: list[tuple[int, str, str]] = []

    result = await call_llm_with_tools_streaming(
        messages=[{"role": "user", "content": "Plan it"}],
        tools=[{"name": "dispatch_subagent"}],
        ctx=StreamingPlanContext(
            executor_id="minimax",
            executor_label="MiniMax",
            model="MiniMax-M2.7",
            endpoint="https://example.test",
            api_key="secret",
            max_tokens=1024,
            timeout_s=10,
        ),
        on_delta=lambda idx, kind, chunk: deltas.append((idx, kind, chunk)),
    )

    assert deltas == [
        (0, "text", "Hello"),
        (1, "tool_input_json", '{"role":"engineer"}'),
    ]
    assert result["stop_reason"] == "tool_use"
    assert result["usage"] == {"output_tokens": 7}
    assert result["content"] == [
        {"type": "text", "text": "Hello"},
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "dispatch_subagent",
            "input": {"role": "engineer"},
        },
    ]


@pytest.mark.asyncio
async def test_stream_llm_skips_non_object_and_malformed_sse_events(monkeypatch):
    monkeypatch.setattr(llm_runner_module.httpx, "AsyncClient", _NoisyStreamClient)

    chunks = [
        chunk
        async for chunk in stream_llm(
            "Plan it",
            StreamingPlanContext(
                executor_id="minimax",
                executor_label="MiniMax",
                model="MiniMax-M2.7",
                endpoint="https://example.test",
                api_key="secret",
                max_tokens=1024,
                timeout_s=10,
            ),
        )
    ]

    assert chunks == ["ok"]


@pytest.mark.asyncio
async def test_llm_http_client_ignores_invalid_ipv6_no_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1,127.0.0.0/8,::1/128")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1,127.0.0.0/8,::1/128")

    async with llm_runner_module._llm_http_client(1.0) as client:
        assert client.timeout.connect == 1.0


@pytest.mark.asyncio
async def test_build_llm_runner_keeps_minimax_m3_retry_prefill_free(monkeypatch):
    _PrefillRetryClient.payloads = []
    monkeypatch.setattr(llm_runner_module.httpx, "AsyncClient", _PrefillRetryClient)

    catalog_service = cast(RuntimeCatalogService, _CatalogService())
    result = await build_llm_runner(catalog_service)("Plan it")

    assert result == '{"items":[]}'
    assert len(_PrefillRetryClient.payloads) == 2
    assert _PrefillRetryClient.payloads[0]["messages"] == [
        {"role": "user", "content": "Plan it"},
    ]
    assert _PrefillRetryClient.payloads[1]["messages"] == [
        {"role": "user", "content": "Plan it"},
    ]


@pytest.mark.asyncio
async def test_build_llm_runner_surfaces_max_tokens_without_returning_truncated_text(
    monkeypatch,
):
    _MaxTokenClient.payloads = []
    monkeypatch.setattr(llm_runner_module.httpx, "AsyncClient", _MaxTokenClient)
    catalog_service = cast(RuntimeCatalogService, _CatalogService())
    runner = build_llm_runner(
        catalog_service,
        max_tokens=16_384,
        raise_on_max_tokens=True,
    )

    with pytest.raises(LLMOutputTokenLimitError, match="max_tokens=16384"):
        await runner("Plan it")

    assert len(_MaxTokenClient.payloads) == 1
    assert _MaxTokenClient.payloads[0]["max_tokens"] == 16_384
