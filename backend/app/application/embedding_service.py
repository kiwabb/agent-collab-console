from __future__ import annotations

"""Optional embedding provider for semantic search.

Configuration source: application/timeouts.py env accessors (so it doesn't require a UI in
this iteration — `runtime_catalog_settings` already exists but embedding
providers are a new concept). Drop-in additions:

  EMBEDDING_API_ENDPOINT   — base URL, e.g. https://api.openai.com/v1
  EMBEDDING_API_KEY        — provider API key
  EMBEDDING_MODEL          — model id, e.g. text-embedding-3-small
  EMBEDDING_PROVIDER_TYPE  — "openai" | "anthropic" | "voyage"  (default: openai)
  EMBEDDING_DISABLED       — "1" to force disable

Failure mode: any missing config → service is disabled, all callers no-op.
"""
import asyncio  # noqa: E402
import hashlib  # noqa: E402
import logging  # noqa: E402
from collections import OrderedDict  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402, F401
from typing import Iterable  # noqa: E402, UP035

import httpx  # noqa: E402

from app.application import timeouts  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingConfig:
    endpoint: str = ""
    api_key: str = ""
    model: str = ""
    provider_type: str = "openai"
    timeout_s: float = 20.0


class EmbeddingService:
    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or self._load_from_env()
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_cap = 512
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        c = self.config
        if timeouts.embedding_disabled():
            return False
        return bool(c.endpoint and c.api_key and c.model)

    @property
    def model_label(self) -> str:
        return f"{self.config.provider_type}/{self.config.model}"

    async def embed_one(self, text: str) -> list[float] | None:
        if not self.enabled:
            return None
        text = (text or "").strip()
        if not text:
            return None
        key = self._cache_key(text)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        try:
            vectors = await self._call_provider([text])
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.info("embedding_service.embed_one failed: %s", exc)
            return None
        if not vectors:
            return None
        vec = vectors[0]
        async with self._lock:
            self._cache[key] = vec
            if len(self._cache) > self._cache_cap:
                self._cache.popitem(last=False)
        return vec

    async def embed_batch(self, texts: Iterable[str]) -> list[list[float] | None]:
        items = [t.strip() if t else "" for t in texts]
        if not any(items):
            return [None] * len(items)
        if not self.enabled:
            return [None] * len(items)
        try:
            vectors = await self._call_provider([t for t in items if t])
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.info("embedding_service.embed_batch failed: %s", exc)
            return [None] * len(items)
        out: list[list[float] | None] = []
        it = iter(vectors)
        for t in items:
            out.append(next(it, None) if t else None)
        return out

    # ------------------------------------------------------------------
    # Provider adapters
    # ------------------------------------------------------------------

    async def _call_provider(self, texts: list[str]) -> list[list[float]]:
        c = self.config
        ptype = (c.provider_type or "openai").lower()
        if ptype in ("openai", "voyage"):
            return await self._call_openai_compatible(texts)
        if ptype == "anthropic":
            # Anthropic doesn't have a public embeddings endpoint yet;
            # treat as openai-compatible at the same path (gateways may
            # offer it). Falls through gracefully if 404.
            return await self._call_openai_compatible(texts)
        raise ValueError(f"unknown embedding provider type: {c.provider_type}")

    async def _call_openai_compatible(self, texts: list[str]) -> list[list[float]]:
        c = self.config
        url = f"{c.endpoint.rstrip('/')}/embeddings"
        payload = {"model": c.model, "input": texts}
        headers = {
            "Authorization": f"Bearer {c.api_key}",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=c.timeout_s) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"embedding HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        out: list[list[float]] = []
        for item in data.get("data") or []:
            vec = item.get("embedding") or []
            if isinstance(vec, list):
                out.append([float(x) for x in vec])
        if len(out) != len(texts):
            logger.debug(
                "embedding_service received %s vectors for %s inputs",
                len(out),
                len(texts),
            )
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        return digest[:32]

    @staticmethod
    def _load_from_env() -> EmbeddingConfig:
        return EmbeddingConfig(
            endpoint=timeouts.embedding_api_endpoint(),
            api_key=timeouts.embedding_api_key(),
            model=timeouts.embedding_model(),
            provider_type=timeouts.embedding_provider_type(),
            timeout_s=timeouts.embedding_timeout_s(),
        )


# Module-level singleton — re-instantiate via get_embedding_service() if env
# changes (most callers don't, since env is read once at process startup).
_singleton: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _singleton
    if _singleton is None:
        _singleton = EmbeddingService()
    return _singleton


def reset_embedding_service(service: EmbeddingService | None = None) -> None:
    """Test hook: replace or clear the singleton."""
    global _singleton
    _singleton = service
