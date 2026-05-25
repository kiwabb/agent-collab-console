"""Dedicated LLM resolution + protocol dispatch for the ProjectConductor loop.

Kept separate from the workflow-orchestrator's `resolve_streaming_context` so the
Conductor's orchestrating brain has its own configurable model/provider/protocol
(catalog.conductor_llm, overridable via CONDUCTOR_LLM_* env). The Conductor loop
only speaks Anthropic-shaped messages; `call_conductor_llm` translates when the
chosen executor's protocol is OpenAI.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from app.application.llm_runner import (
    DeltaCallback,
    StreamingPlanContext,
    _pick_executor,
    _resolve_model,
    call_llm_with_tools,
    call_llm_with_tools_streaming,
    call_openai_with_tools,
    call_openai_with_tools_streaming,
)

logger = logging.getLogger(__name__)


@dataclass
class ConductorLLMContext:
    ctx: StreamingPlanContext
    protocol: str  # "anthropic" | "openai"


def _env_or(value: str | None, fallback):
    return value if value not in (None, "") else fallback


def resolve_conductor_llm_context(catalog) -> ConductorLLMContext | None:
    """Resolve the Conductor's own LLM endpoint/model/protocol from the catalog.

    Selection precedence: CONDUCTOR_LLM_* env > catalog.conductor_llm > the same
    executor-picking heuristic the orchestrator uses. Protocol is taken from the
    chosen executor's `protocol` field (overridable via CONDUCTOR_LLM_PROTOCOL).
    """
    cfg = getattr(catalog, "conductor_llm", None)
    preferred_executor_id = _env_or(
        os.getenv("CONDUCTOR_LLM_EXECUTOR_ID"),
        getattr(cfg, "executor_id", None) if cfg else None,
    )
    preferred_model = _env_or(
        os.getenv("CONDUCTOR_LLM_MODEL"),
        getattr(cfg, "model", None) if cfg else None,
    )
    max_tokens = int(_env_or(
        os.getenv("CONDUCTOR_LLM_MAX_TOKENS"),
        getattr(cfg, "max_tokens", None) if cfg else None,
    ) or 8192)
    timeout_s = float(_env_or(
        os.getenv("CONDUCTOR_LLM_TIMEOUT"),
        getattr(cfg, "timeout_s", None) if cfg else None,
    ) or 120.0)

    executor = _pick_executor(catalog, preferred_executor_id)
    if executor is None:
        return None
    model = _resolve_model(executor, preferred_model)
    if not model:
        return None
    protocol = str(
        _env_or(os.getenv("CONDUCTOR_LLM_PROTOCOL"), getattr(executor, "protocol", None)) or "anthropic"
    ).lower()
    if protocol not in ("anthropic", "openai"):
        protocol = "anthropic"
    ctx = StreamingPlanContext(
        executor_id=executor.id,
        executor_label=executor.label or executor.id,
        model=model,
        endpoint=executor.api_endpoint.rstrip("/"),
        api_key=executor.api_key,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    )
    return ConductorLLMContext(ctx=ctx, protocol=protocol)


async def call_conductor_llm(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    cllm: ConductorLLMContext,
    on_delta: DeltaCallback | None = None,
) -> dict[str, Any]:
    """Call the Conductor's LLM via the right protocol; return an Anthropic-shaped message."""
    if cllm.protocol == "openai":
        if on_delta is not None:
            return await call_openai_with_tools_streaming(
                messages=messages, tools=tools, ctx=cllm.ctx, on_delta=on_delta
            )
        return await call_openai_with_tools(messages=messages, tools=tools, ctx=cllm.ctx)
    if on_delta is not None:
        return await call_llm_with_tools_streaming(
            messages=messages, tools=tools, ctx=cllm.ctx, on_delta=on_delta
        )
    return await call_llm_with_tools(messages=messages, tools=tools, ctx=cllm.ctx)
