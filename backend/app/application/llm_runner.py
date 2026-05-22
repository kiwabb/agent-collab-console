"""Thin LLM caller used by the workflow orchestrator's Auto-plan.

Resolves an executor/model from the runtime catalog (or env override) and
sends a single Anthropic-compatible /v1/messages request. Returns the
assistant's text content, or None on any failure — callers (see
`WorkflowOrchestrator._llm_propose`) silently fall back to the heuristic
plan on None, so this function intentionally swallows errors and logs
them.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from app.application.runtime_catalog_service import RuntimeCatalogService
from app.domain.models import RuntimeExecutorConfig

logger = logging.getLogger(__name__)

# Module-level singleton so a single API call doesn't re-load the catalog
# more than necessary, but we re-resolve on each invocation in case the
# user edited it.
LLM_RUNNER_TYPE = Callable[[str], Awaitable[str | None]]
DeltaCallback = Callable[[int, str, str], Awaitable[None] | None]


def extract_tool_use_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Return valid Anthropic `tool_use` content blocks from a message."""
    blocks = message.get("content") if isinstance(message, dict) else None
    if not isinstance(blocks, list):
        return []
    tool_uses: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if not block.get("id") or not block.get("name"):
            continue
        tool_input = block.get("input")
        if tool_input is not None and not isinstance(tool_input, dict):
            continue
        tool_uses.append(
            {
                "type": "tool_use",
                "id": str(block["id"]),
                "name": str(block["name"]),
                "input": tool_input or {},
            }
        )
    return tool_uses


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
    # 28s default — Next.js dev proxy has a hard 30s rewrite window, so the
    # backend must finish (or fall back to the heuristic) within it. Sonnet
    # 4.6 fits ~26-29s; Haiku 4.5 fits ~5s. Use Haiku via
    # WORKFLOW_ORCHESTRATOR_MODEL=claude-haiku-4-5 if responses are too slow.
    timeout_s = float(os.getenv("WORKFLOW_ORCHESTRATOR_TIMEOUT", "28"))
    # 8192 leaves comfortable headroom for: a) the DAG JSON itself, b) the
    # chain-of-thought / preamble some models (notably MiniMax) emit before
    # the actual JSON, and c) Chinese-language rationale (≈2× the token
    # density of English). Streaming means we don't pay the round-trip for
    # unused budget — tokens flow as they're generated and the bound only
    # matters as an upper cap.
    max_tokens = int(os.getenv("WORKFLOW_ORCHESTRATOR_MAX_TOKENS", "8192"))

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
            # Assistant-prefill (see stream_llm for the rationale). The
            # leading "{" is NOT in the model's response, so we prepend it
            # before returning so json.loads sees a complete object.
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": "{"},
                ],
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
            if not text:
                return None
            # Prepend the prefilled "{" only when the model continued AFTER it
            # (Anthropic native). Some gateways (MiniMax) ignore the prefill
            # and re-emit "{" themselves; in that case skip the prepend so we
            # don't end up with "{{".
            stripped = text.lstrip()
            if not stripped.startswith("{"):
                return "{" + text
            return text
        except httpx.TimeoutException:
            logger.warning("Auto-plan: LLM request timed out after %ss", timeout_s)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto-plan: LLM runner error: %s", exc)
            return None

    return runner


# --- Streaming variant for /plan/stream ---


@dataclass
class StreamingPlanContext:
    """The resolved executor + model the streaming endpoint chose. Useful for
    emitting a `meta` event up front so the UI can show which LLM is talking.
    """
    executor_id: str
    executor_label: str
    model: str
    endpoint: str
    api_key: str
    max_tokens: int
    timeout_s: float


def resolve_streaming_context(catalog) -> StreamingPlanContext | None:
    """Mirror of the picks build_llm_runner makes, but exposed so the SSE
    endpoint can announce which model is about to be called before the first
    token arrives."""
    preferred_executor_id = os.getenv("WORKFLOW_ORCHESTRATOR_EXECUTOR_ID") or None
    preferred_model_id = os.getenv("WORKFLOW_ORCHESTRATOR_MODEL") or None
    timeout_s = float(os.getenv("WORKFLOW_ORCHESTRATOR_TIMEOUT", "28"))
    # Same default as the non-streaming runner — see comment there.
    max_tokens = int(os.getenv("WORKFLOW_ORCHESTRATOR_MAX_TOKENS", "8192"))
    executor = _pick_executor(catalog, preferred_executor_id)
    if executor is None:
        return None
    model = _resolve_model(executor, preferred_model_id)
    if not model:
        return None
    return StreamingPlanContext(
        executor_id=executor.id,
        executor_label=executor.label or executor.id,
        model=model,
        endpoint=executor.api_endpoint.rstrip("/"),
        api_key=executor.api_key,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    )


async def stream_llm(prompt: str, ctx: StreamingPlanContext) -> AsyncIterator[str]:
    """Stream text deltas from an Anthropic-compatible /v1/messages SSE.

    Anthropic shape (also honored by the MiniMax compat gateway):
        event: content_block_delta
        data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"..."}}

    Yields each `text_delta.text` chunk. Stops on `message_stop` or stream
    close. Raises on transport-level errors (the caller catches and emits a
    fallback event).
    """
    url = f"{ctx.endpoint}/v1/messages"
    # Assistant-prefill trick: by ending the messages array with an empty-ish
    # assistant turn that starts with "{", we force the model to continue
    # generating from inside an open JSON object — no preamble, no markdown
    # fence, no "Here is the DAG:". Anthropic and most compatible gateways
    # (MiniMax included) honor this. The leading "{" we prefill is NOT in the
    # streamed response, so we re-prepend it to the accumulated text before
    # parsing. (Done by the caller via the `assistant_prefill` field below.)
    payload = {
        "model": ctx.model,
        "max_tokens": ctx.max_tokens,
        "stream": True,
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "{"},
        ],
    }
    headers = {
        "x-api-key": ctx.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }
    # Note: we do NOT pre-yield the prefilled "{". Some compatible gateways
    # (e.g. MiniMax) ignore the prefill and re-emit "{" themselves, so adding
    # our own would produce "{{". Callers must handle the case where the
    # accumulated stream may or may not start with "{" (see `_extract_first_json_object`
    # in the SSE endpoint — it prepends "{" if missing).
    async with httpx.AsyncClient(timeout=ctx.timeout_s) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"LLM stream HTTP {response.status_code}: {body[:300]!r}"
                )
            async for line in response.aiter_lines():
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw in ("", "[DONE]"):
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text") or ""
                        if text:
                            yield text
                elif etype == "message_stop":
                    return


async def call_llm_with_tools(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    ctx: StreamingPlanContext,
) -> dict[str, Any]:
    """Call an Anthropic-compatible messages endpoint with tool definitions."""
    url = f"{ctx.endpoint}/v1/messages"
    payload: dict[str, Any] = {
        "model": ctx.model,
        "max_tokens": ctx.max_tokens,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
    async with httpx.AsyncClient(timeout=ctx.timeout_s) as client:
        response = await client.post(
            url,
            headers={
                "x-api-key": ctx.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
    if response.status_code != 200:
        raise RuntimeError(f"LLM tools HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if extract_tool_use_blocks(data):
        return data
    if not isinstance(data.get("content"), list):
        data["content"] = []
    return data


async def call_llm_with_tools_streaming(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    ctx: StreamingPlanContext,
    on_delta: DeltaCallback | None = None,
    batch_window_ms: int = 100,
) -> dict[str, Any]:
    """Stream an Anthropic-compatible messages response and reconstruct the final message.

    Emits batched `text` and `tool_input_json` deltas through `on_delta`, while
    returning a complete assistant message payload at the end.
    """
    url = f"{ctx.endpoint}/v1/messages"
    payload: dict[str, Any] = {
        "model": ctx.model,
        "max_tokens": ctx.max_tokens,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools

    headers = {
        "x-api-key": ctx.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }
    block_order: list[int] = []
    blocks: dict[int, dict[str, Any]] = {}
    pending_chunks: dict[tuple[int, str], str] = {}
    last_flush = time.monotonic()
    stop_reason: str | None = None
    usage: dict[str, Any] | None = None

    async def emit_delta(index: int, kind: str, chunk: str) -> None:
        if not chunk or on_delta is None:
            return
        result = on_delta(index, kind, chunk)
        if hasattr(result, "__await__"):
            await result

    async def flush_pending(force: bool = False) -> None:
        nonlocal last_flush
        if not pending_chunks:
            if force:
                last_flush = time.monotonic()
            return
        now = time.monotonic()
        if not force and (now - last_flush) * 1000 < batch_window_ms:
            return
        items = list(pending_chunks.items())
        pending_chunks.clear()
        last_flush = now
        for (index, kind), chunk in items:
            await emit_delta(index, kind, chunk)

    async with httpx.AsyncClient(timeout=ctx.timeout_s) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"LLM tools stream HTTP {response.status_code}: {body[:300]!r}"
                )
            async for line in response.aiter_lines():
                if not line:
                    await flush_pending()
                    continue
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw in ("", "[DONE]"):
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")
                if etype == "message_start":
                    message = event.get("message") or {}
                    if isinstance(message.get("usage"), dict):
                        usage = dict(message["usage"])
                elif etype == "content_block_start":
                    index = int(event.get("index") or 0)
                    content_block = event.get("content_block") or {}
                    block_type = str(content_block.get("type") or "text")
                    if index not in blocks:
                        block_order.append(index)
                    if block_type == "tool_use":
                        blocks[index] = {
                            "type": "tool_use",
                            "id": str(content_block.get("id") or ""),
                            "name": str(content_block.get("name") or ""),
                            "input_json": "",
                        }
                    else:
                        blocks[index] = {
                            "type": "text",
                            "text": str(content_block.get("text") or ""),
                        }
                elif etype == "content_block_delta":
                    index = int(event.get("index") or 0)
                    delta = event.get("delta") or {}
                    delta_type = delta.get("type")
                    block = blocks.setdefault(index, {"type": "text", "text": ""})
                    if index not in block_order:
                        block_order.append(index)
                    if delta_type == "text_delta":
                        chunk = str(delta.get("text") or "")
                        if chunk:
                            block["type"] = "text"
                            block["text"] = str(block.get("text") or "") + chunk
                            pending_chunks[(index, "text")] = pending_chunks.get((index, "text"), "") + chunk
                    elif delta_type == "input_json_delta":
                        chunk = str(delta.get("partial_json") or "")
                        if chunk:
                            block["type"] = "tool_use"
                            block["input_json"] = str(block.get("input_json") or "") + chunk
                            pending_chunks[(index, "tool_input_json")] = pending_chunks.get((index, "tool_input_json"), "") + chunk
                    await flush_pending()
                elif etype == "message_delta":
                    delta = event.get("delta") or {}
                    if delta.get("stop_reason") is not None:
                        stop_reason = str(delta.get("stop_reason"))
                    if isinstance(event.get("usage"), dict):
                        usage = dict(event["usage"])
                elif etype == "content_block_stop":
                    await flush_pending(force=True)
                elif etype == "message_stop":
                    await flush_pending(force=True)
                    break

    content: list[dict[str, Any]] = []
    for index in sorted(block_order):
        block = blocks.get(index) or {}
        if block.get("type") == "tool_use":
            input_json = str(block.get("input_json") or "").strip()
            try:
                tool_input = json.loads(input_json) if input_json else {}
            except json.JSONDecodeError:
                tool_input = {}
            content.append(
                {
                    "type": "tool_use",
                    "id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "input": tool_input if isinstance(tool_input, dict) else {},
                }
            )
            continue
        text = str(block.get("text") or "")
        if text:
            content.append({"type": "text", "text": text})

    return {
        "role": "assistant",
        "content": content,
        "stop_reason": stop_reason or "end_turn",
        "usage": usage or {},
    }
