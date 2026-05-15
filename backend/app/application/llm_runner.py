"""Thin LLM caller used by the workflow orchestrator's Auto-plan.

Resolves an executor/model from the runtime catalog (or env override) and
sends a single Anthropic-compatible /v1/messages request. Returns the
assistant's text content, or None on any failure — callers (see
`WorkflowOrchestrator._llm_propose`) silently fall back to the heuristic
plan on None, so this function intentionally swallows errors and logs
them.
"""

from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable

import httpx

from app.application.runtime_catalog_service import RuntimeCatalogService
from app.domain.models import RuntimeExecutorConfig

logger = logging.getLogger(__name__)

# Module-level singleton so a single API call doesn't re-load the catalog
# more than necessary, but we re-resolve on each invocation in case the
# user edited it.
LLM_RUNNER_TYPE = Callable[[str], Awaitable[str | None]]


def _pick_executor(
    catalog,
    preferred_id: str | None,
) -> RuntimeExecutorConfig | None:
    """Pick a usable executor.

    Order of preference:
      1. The executor whose id matches `preferred_id` (env override).
      2. An executor with `executor_type == "claude"` that is enabled and
         has both api_endpoint + api_key.
      3. Any enabled executor with api_endpoint + api_key.
    """
    if preferred_id:
        for e in catalog.executors:
            if e.id == preferred_id and e.api_endpoint and e.api_key:
                return e
    for e in catalog.executors:
        if (
            e.enabled
            and getattr(e, "executor_type", "claude") == "claude"
            and e.api_endpoint
            and e.api_key
        ):
            return e
    for e in catalog.executors:
        if e.enabled and e.api_endpoint and e.api_key:
            return e
    return None


def _resolve_model(executor: RuntimeExecutorConfig, preferred_model: str | None) -> str | None:
    if preferred_model:
        return preferred_model
    if executor.default_model:
        return executor.default_model
    # Fall back to the default provider's default model.
    provider_id = getattr(executor, "default_provider_id", None)
    if provider_id:
        provider = next((p for p in executor.providers if p.id == provider_id), None)
        if provider and getattr(provider, "default_model_id", None):
            return provider.default_model_id
    # Otherwise grab the first enabled model on the first enabled provider.
    for p in executor.providers:
        if not p.enabled:
            continue
        for m in p.models:
            if m.enabled:
                return m.id
    return None


def build_llm_runner(catalog_service: RuntimeCatalogService) -> LLM_RUNNER_TYPE:
    """Return an async callable that turns a prompt into assistant text."""
    preferred_executor_id = os.getenv("WORKFLOW_ORCHESTRATOR_EXECUTOR_ID") or None
    preferred_model_id = os.getenv("WORKFLOW_ORCHESTRATOR_MODEL") or None
    timeout_s = float(os.getenv("WORKFLOW_ORCHESTRATOR_TIMEOUT", "60"))
    max_tokens = int(os.getenv("WORKFLOW_ORCHESTRATOR_MAX_TOKENS", "2048"))

    async def runner(prompt: str) -> str | None:
        try:
            catalog = await catalog_service.load_catalog()
            executor = _pick_executor(catalog, preferred_executor_id)
            if executor is None:
                logger.info("Auto-plan: no usable executor configured; falling back to heuristic")
                return None
            model = _resolve_model(executor, preferred_model_id)
            if not model:
                logger.info("Auto-plan: executor %s has no resolvable model; falling back", executor.id)
                return None

            url = f"{executor.api_endpoint.rstrip('/')}/v1/messages"
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(
                    url,
                    headers={
                        "x-api-key": executor.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
            if response.status_code != 200:
                logger.warning(
                    "Auto-plan: LLM returned HTTP %s: %s",
                    response.status_code,
                    response.text[:300],
                )
                return None
            data = response.json()
            # Anthropic shape: { "content": [ { "type": "text", "text": "..." }, ... ], ... }
            parts = data.get("content") or []
            text = "".join(
                p.get("text", "")
                for p in parts
                if isinstance(p, dict) and p.get("type") == "text"
            )
            return text or None
        except httpx.TimeoutException:
            logger.warning("Auto-plan: LLM request timed out after %ss", timeout_s)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto-plan: LLM runner error: %s", exc)
            return None

    return runner
