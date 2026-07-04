"""Tests for embedding_service — focus on the disabled path + cache."""

from __future__ import annotations

import asyncio  # noqa: F401

import pytest

from app.application.embedding_service import EmbeddingConfig, EmbeddingService


def test_disabled_when_endpoint_missing():
    svc = EmbeddingService(EmbeddingConfig(endpoint="", api_key="k", model="m"))
    assert not svc.enabled


def test_disabled_when_api_key_missing():
    svc = EmbeddingService(EmbeddingConfig(endpoint="http://x", api_key="", model="m"))
    assert not svc.enabled


def test_disabled_when_model_missing():
    svc = EmbeddingService(EmbeddingConfig(endpoint="http://x", api_key="k", model=""))
    assert not svc.enabled


def test_enabled_when_all_present(monkeypatch):
    monkeypatch.delenv("EMBEDDING_DISABLED", raising=False)
    svc = EmbeddingService(EmbeddingConfig(endpoint="http://x", api_key="k", model="m"))
    assert svc.enabled


def test_env_flag_force_disables(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DISABLED", "true")
    svc = EmbeddingService(EmbeddingConfig(endpoint="http://x", api_key="k", model="m"))
    assert not svc.enabled


def test_load_from_env_uses_safe_defaults(monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_ENDPOINT", " https://emb.example/v1 ")
    monkeypatch.setenv("EMBEDDING_API_KEY", " key-1 ")
    monkeypatch.setenv("EMBEDDING_MODEL", " model-1 ")
    monkeypatch.setenv("EMBEDDING_PROVIDER_TYPE", " ")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_S", "not-a-float")

    cfg = EmbeddingService._load_from_env()

    assert cfg.endpoint == "https://emb.example/v1"
    assert cfg.api_key == "key-1"
    assert cfg.model == "model-1"
    assert cfg.provider_type == "openai"
    assert cfg.timeout_s == 20.0


@pytest.mark.asyncio
async def test_embed_one_returns_none_when_disabled():
    svc = EmbeddingService(EmbeddingConfig())
    out = await svc.embed_one("hello world")
    assert out is None


@pytest.mark.asyncio
async def test_embed_one_returns_none_for_empty_text():
    svc = EmbeddingService(EmbeddingConfig(endpoint="http://x", api_key="k", model="m"))

    async def fake_call(texts):
        return [[1.0, 0.0]]

    svc._call_provider = fake_call  # type: ignore[assignment]
    assert await svc.embed_one("") is None
    assert await svc.embed_one("   ") is None


@pytest.mark.asyncio
async def test_embed_one_uses_cache(monkeypatch):
    svc = EmbeddingService(EmbeddingConfig(endpoint="http://x", api_key="k", model="m"))
    calls = {"n": 0}

    async def fake_call(texts):
        calls["n"] += 1
        return [[float(len(t))] for t in texts]

    svc._call_provider = fake_call  # type: ignore[assignment]
    a = await svc.embed_one("hello")
    b = await svc.embed_one("hello")
    assert a == b
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_embed_one_swallows_provider_errors():
    svc = EmbeddingService(EmbeddingConfig(endpoint="http://x", api_key="k", model="m"))

    async def boom(texts):
        raise RuntimeError("provider exploded")

    svc._call_provider = boom  # type: ignore[assignment]
    assert await svc.embed_one("anything") is None


def test_model_label_format():
    svc = EmbeddingService(
        EmbeddingConfig(
            endpoint="http://x",
            api_key="k",
            model="text-embedding-3-small",
            provider_type="openai",
        )
    )
    assert svc.model_label == "openai/text-embedding-3-small"
