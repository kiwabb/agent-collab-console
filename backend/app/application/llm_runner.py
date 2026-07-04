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
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable  # noqa: UP035

import httpx

from app.application import timeouts
from app.application.runtime_catalog_service import RuntimeCatalogService
from app.domain.models import RuntimeExecutorConfig

logger = logging.getLogger(__name__)

# Module-level singleton so a single API call doesn't re-load the catalog
# more than necessary, but we re-resolve on each invocation in case the
# user edited it.
LLM_RUNNER_TYPE = Callable[[str], Awaitable[str | None]]
DeltaCallback = Callable[[int, str, str], Awaitable[None] | None]


@dataclass(frozen=True)
class WorkflowOrchestratorLLMConfig:
    preferred_executor_id: str | None
    preferred_model_id: str | None
    timeout_s: float
    max_tokens: int


def _workflow_orchestrator_llm_config() -> WorkflowOrchestratorLLMConfig:
    return WorkflowOrchestratorLLMConfig(
        preferred_executor_id=timeouts.workflow_orchestrator_executor_id(),
        preferred_model_id=timeouts.workflow_orchestrator_model(),
        timeout_s=timeouts.workflow_orchestrator_timeout_s(),
        max_tokens=timeouts.workflow_orchestrator_max_tokens(),
    )


def _audit_autoplan(
    category: str,
    *,
    executor_id: str | None,
    model: str | None,
    payload: dict[str, Any] | None = None,
    status: str | None = None,
    started: float | None = None,
    error: str | None = None,
) -> None:
    """Record an auto-plan LLM call/return into the unified audit_log (PR2).

    Best-effort + fire-and-forget. The auto-plan path has no issue/task context
    (it runs for the workflow orchestrator before any issue task exists), so it
    audits actor + executor/model + a small payload only. Never raises into the
    runner, which already swallows its own errors and falls back to heuristics.
    """
    from app.application import audit

    audit.record_autoplan(
        category,
        executor_id=executor_id,
        model=model,
        payload=payload,
        status=status,
        started=started,
        error=error,
    )


def _sanitize_http_error(status_code: int, body: str) -> str:
    """Return a clean error string — strips HTML bodies to avoid leaking page markup."""
    stripped = body.strip()
    if stripped.lower().startswith("<!doctype") or stripped.lower().startswith("<html"):
        return f"HTTP {status_code}: server returned an HTML page (not JSON) — check API endpoint and key"
    return f"HTTP {status_code}: {stripped[:200]}"


def _llm_http_client(timeout_s: float) -> httpx.AsyncClient:
    """Create LLM HTTP clients isolated from local proxy env parsing."""
    return httpx.AsyncClient(timeout=timeout_s, trust_env=False)


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
    config = _workflow_orchestrator_llm_config()

    async def runner(prompt: str) -> str | None:
        try:
            catalog = await catalog_service.load_catalog()
            executor = _pick_executor(catalog, config.preferred_executor_id)
            if executor is None:
                logger.info("Auto-plan: no usable executor configured; falling back to heuristic")
                return None
            model = _resolve_model(executor, config.preferred_model_id)
            if not model:
                logger.info(
                    "Auto-plan: executor %s has no resolvable model; falling back", executor.id
                )
                return None

            url = llm_api_url(executor.api_endpoint, "/v1/messages")
            # Assistant-prefill (see stream_llm for the rationale). The
            # leading "{" is NOT in the model's response, so we prepend it
            # before returning so json.loads sees a complete object.
            payload = {
                "model": model,
                "max_tokens": config.max_tokens,
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": "{"},
                ],
            }
            # Audit the auto-plan LLM call (PR2): previously this path only
            # emitted WARNING-level stderr and never entered conductor_turns.
            _audit_autoplan(
                "llm_call",
                executor_id=executor.id,
                model=model,
                payload={"prompt_chars": len(prompt), "max_tokens": config.max_tokens},
            )
            _call_started = time.monotonic()
            async with _llm_http_client(config.timeout_s) as client:
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
                _audit_autoplan(
                    "llm_return",
                    executor_id=executor.id,
                    model=model,
                    status="error",
                    started=_call_started,
                    payload={"http_status": response.status_code},
                    error=f"HTTP {response.status_code}",
                )
                return None
            data = response.json()
            _audit_autoplan(
                "llm_return",
                executor_id=executor.id,
                model=model,
                status="ok",
                started=_call_started,
                payload={
                    "http_status": response.status_code,
                    "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
                    "stop_reason": data.get("stop_reason"),
                },
            )
            # Anthropic shape: { "content": [ { "type": "text", "text": "..." }, ... ], ... }
            parts = data.get("content") or []
            text = "".join(
                p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"
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
            logger.warning("Auto-plan: LLM request timed out after %ss", config.timeout_s)
            return None
        except Exception as exc:  # noqa: BLE001, RUF100
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


def llm_api_url(endpoint: str, api_path: str) -> str:
    """Join an LLM endpoint with an API path without duplicating `/v1`.

    The UI and provider docs commonly describe OpenAI-compatible base URLs as
    `.../v1`, while this backend historically stored provider roots and appended
    `/v1/...` itself. Accept both shapes so runtime catalog tests and conductor
    calls behave like users expect.
    """
    base = endpoint.rstrip("/")
    path = api_path if api_path.startswith("/") else f"/{api_path}"
    if base.endswith("/v1") and path.startswith("/v1/"):
        return f"{base}{path[3:]}"
    return f"{base}{path}"


def resolve_streaming_context(catalog) -> StreamingPlanContext | None:
    """Mirror of the picks build_llm_runner makes, but exposed so the SSE
    endpoint can announce which model is about to be called before the first
    token arrives."""
    config = _workflow_orchestrator_llm_config()
    executor = _pick_executor(catalog, config.preferred_executor_id)
    if executor is None:
        return None
    model = _resolve_model(executor, config.preferred_model_id)
    if not model:
        return None
    return StreamingPlanContext(
        executor_id=executor.id,
        executor_label=executor.label or executor.id,
        model=model,
        endpoint=executor.api_endpoint.rstrip("/"),
        api_key=executor.api_key,
        max_tokens=config.max_tokens,
        timeout_s=config.timeout_s,
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
    url = llm_api_url(ctx.endpoint, "/v1/messages")
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
    async with _llm_http_client(ctx.timeout_s) as client:  # noqa: SIM117
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(f"LLM stream HTTP {response.status_code}: {body[:300]!r}")
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
    url = llm_api_url(ctx.endpoint, "/v1/messages")
    payload: dict[str, Any] = {
        "model": ctx.model,
        "max_tokens": ctx.max_tokens,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
    async with _llm_http_client(ctx.timeout_s) as client:
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
        raise RuntimeError(f"LLM tools {_sanitize_http_error(response.status_code, response.text)}")
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
    url = llm_api_url(ctx.endpoint, "/v1/messages")
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

    async with _llm_http_client(ctx.timeout_s) as client:  # noqa: SIM117
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(f"LLM tools stream HTTP {response.status_code}: {body[:300]!r}")
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
                            pending_chunks[(index, "text")] = (
                                pending_chunks.get((index, "text"), "") + chunk
                            )
                    elif delta_type == "input_json_delta":
                        chunk = str(delta.get("partial_json") or "")
                        if chunk:
                            block["type"] = "tool_use"
                            block["input_json"] = str(block.get("input_json") or "") + chunk
                            pending_chunks[(index, "tool_input_json")] = (
                                pending_chunks.get((index, "tool_input_json"), "") + chunk
                            )
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


# ---------------------------------------------------------------------------
# OpenAI Chat Completions protocol adapter.
#
# The Conductor loop only understands Anthropic-shaped messages
# ({role, content:[{type:text|tool_use|...}]}). These helpers translate to/from
# the OpenAI /v1/chat/completions wire format so an OpenAI-protocol endpoint can
# drive the exact same loop. All public functions return Anthropic-shaped dicts.
# ---------------------------------------------------------------------------


def _anthropic_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description") or "",
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
        )
    return out


def _anthropic_messages_to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the conductor's Anthropic message list to OpenAI chat messages."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            out.append({"role": role, "content": ""})
            continue
        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text") or ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": str(block.get("id") or ""),
                            "type": "function",
                            "function": {
                                "name": str(block.get("name") or ""),
                                "arguments": json.dumps(
                                    block.get("input") or {}, ensure_ascii=False
                                ),
                            },
                        }
                    )
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            assistant_msg["content"] = "".join(text_parts) or None
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            out.append(assistant_msg)
        else:
            # user turn: may carry tool_result blocks -> one OpenAI "tool" msg each.
            tool_results = [
                b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
            if tool_results:
                for block in tool_results:
                    raw = block.get("content")
                    text = (
                        raw
                        if isinstance(raw, str)
                        else json.dumps(raw, ensure_ascii=False, default=str)
                    )
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(block.get("tool_use_id") or ""),
                            "content": text,
                        }
                    )
            else:
                text_parts = [
                    str(b.get("text") or "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                out.append({"role": "user", "content": "".join(text_parts)})
    return out


def _openai_choice_to_anthropic(
    message: dict[str, Any], finish_reason: str | None, usage: dict[str, Any] | None
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        content.append({"type": "text", "text": text})
    for tc in message.get("tool_calls") or []:
        fn = (tc or {}).get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        try:
            tool_input = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except json.JSONDecodeError:
            tool_input = {}
        content.append(
            {
                "type": "tool_use",
                "id": str(tc.get("id") or ""),
                "name": str(fn.get("name") or ""),
                "input": tool_input if isinstance(tool_input, dict) else {},
            }
        )
    stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
    anthropic_usage: dict[str, Any] = {}
    if isinstance(usage, dict):
        anthropic_usage = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }
    return {
        "role": "assistant",
        "content": content,
        "stop_reason": stop_reason,
        "usage": anthropic_usage,
    }


async def call_openai_with_tools(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    ctx: StreamingPlanContext,
) -> dict[str, Any]:
    """Call an OpenAI-compatible /v1/chat/completions endpoint; return Anthropic shape."""
    url = llm_api_url(ctx.endpoint, "/v1/chat/completions")
    payload: dict[str, Any] = {
        "model": ctx.model,
        "max_tokens": ctx.max_tokens,
        "messages": _anthropic_messages_to_openai(messages),
    }
    openai_tools = _anthropic_tools_to_openai(tools)
    if openai_tools:
        payload["tools"] = openai_tools
    async with _llm_http_client(ctx.timeout_s) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {ctx.api_key}",
                "content-type": "application/json",
            },
            json=payload,
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenAI tools {_sanitize_http_error(response.status_code, response.text)}"
        )
    data = response.json()
    choice = (data.get("choices") or [{}])[0]
    return _openai_choice_to_anthropic(
        choice.get("message") or {},
        choice.get("finish_reason"),
        data.get("usage"),
    )


async def call_openai_with_tools_streaming(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    ctx: StreamingPlanContext,
    on_delta: DeltaCallback | None = None,
) -> dict[str, Any]:
    """Stream an OpenAI-compatible chat completion, reconstructing an Anthropic message.

    Emits the same `on_delta(content_block_index, kind, chunk)` contract as the
    Anthropic streamer: text -> kind "text" at block 0; tool-call arguments ->
    kind "tool_input_json" at block (openai_index + 1).
    """
    url = llm_api_url(ctx.endpoint, "/v1/chat/completions")
    payload: dict[str, Any] = {
        "model": ctx.model,
        "max_tokens": ctx.max_tokens,
        "messages": _anthropic_messages_to_openai(messages),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    openai_tools = _anthropic_tools_to_openai(tools)
    if openai_tools:
        payload["tools"] = openai_tools
    headers = {
        "Authorization": f"Bearer {ctx.api_key}",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }

    text_acc = ""
    # tool_calls accumulated by OpenAI delta index -> {id, name, args}
    tool_acc: dict[int, dict[str, str]] = {}
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    async def emit(block_index: int, kind: str, chunk: str) -> None:
        if not chunk or on_delta is None:
            return
        result = on_delta(block_index, kind, chunk)
        if hasattr(result, "__await__"):
            await result

    async with _llm_http_client(ctx.timeout_s) as client:  # noqa: SIM117
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"OpenAI tools stream HTTP {response.status_code}: {body[:300]!r}"
                )
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw in ("", "[DONE]"):
                    if raw == "[DONE]":
                        break
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(event.get("usage"), dict):
                    usage = dict(event["usage"])
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason"))
                content_chunk = delta.get("content")
                if isinstance(content_chunk, str) and content_chunk:
                    text_acc += content_chunk
                    await emit(0, "text", content_chunk)
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index") or 0)
                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = str(tc["id"])
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = str(fn["name"])
                    arg_chunk = fn.get("arguments")
                    if isinstance(arg_chunk, str) and arg_chunk:
                        slot["args"] += arg_chunk
                        await emit(idx + 1, "tool_input_json", arg_chunk)

    content: list[dict[str, Any]] = []
    if text_acc:
        content.append({"type": "text", "text": text_acc})
    for idx in sorted(tool_acc.keys()):
        slot = tool_acc[idx]
        args_str = slot["args"].strip()
        try:
            tool_input = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            tool_input = {}
        content.append(
            {
                "type": "tool_use",
                "id": slot["id"],
                "name": slot["name"],
                "input": tool_input if isinstance(tool_input, dict) else {},
            }
        )
    anthropic_usage: dict[str, Any] = {}
    if isinstance(usage, dict):
        anthropic_usage = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }
    return {
        "role": "assistant",
        "content": content,
        "stop_reason": "tool_use" if finish_reason == "tool_calls" else "end_turn",
        "usage": anthropic_usage,
    }
