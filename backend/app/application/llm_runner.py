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
from typing import Awaitable, Callable, Protocol  # noqa: UP035
from uuid import uuid4

import httpx

from app.application import timeouts
from app.application.runtime_catalog_service import RuntimeCatalogService
from app.domain.models import AgentCallTrace, RuntimeCatalog, RuntimeExecutorConfig
from app.json_safety import JsonObject, object_dict, parse_json_object, string_value

logger = logging.getLogger(__name__)

# Module-level singleton so a single API call doesn't re-load the catalog
# more than necessary, but we re-resolve on each invocation in case the
# user edited it.
LLM_RUNNER_TYPE = Callable[[str], Awaitable[str | None]]
DeltaCallback = Callable[[int, str, str], Awaitable[None] | None]
TRACE_PAYLOAD_LIMIT = 50_000
TRACE_PREVIEW_LIMIT = 4_000
SENSITIVE_TRACE_KEYS = frozenset({"api_key", "authorization", "token", "password", "secret"})


class LLMOutputTokenLimitError(RuntimeError):
    """The provider stopped before completing the requested model output."""


class AgentCallTraceStore(Protocol):
    async def save_agent_call_trace(self, trace: AgentCallTrace) -> None: ...


@dataclass(frozen=True)
class WorkflowOrchestratorLLMConfig:
    preferred_executor_id: str | None
    preferred_model_id: str | None
    timeout_s: float
    max_tokens: int


@dataclass(frozen=True)
class ResolvedRuntimeExecutor:
    config: RuntimeExecutorConfig
    api_endpoint: str
    api_key: str


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
    payload: JsonObject | None = None,
    status: str | None = None,
    started: float | None = None,
    error: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
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
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
    )


def _redact_trace_value(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(secret_key in lowered for secret_key in SENSITIVE_TRACE_KEYS):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_trace_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_trace_value(item) for item in value]
    return value


def _trace_json_and_preview(value: object) -> tuple[str, str, bool]:
    redacted = _redact_trace_value(value)
    raw = json.dumps(redacted, ensure_ascii=False, default=str)
    preview = raw[:TRACE_PREVIEW_LIMIT]
    if len(raw) <= TRACE_PAYLOAD_LIMIT:
        return raw, preview, False
    truncated = {
        "__truncated__": True,
        "preview": raw[:TRACE_PAYLOAD_LIMIT],
        "original_length": len(raw),
    }
    return json.dumps(truncated, ensure_ascii=False), preview, True


async def _save_autoplan_trace(
    trace_store: AgentCallTraceStore | None,
    *,
    trace_id: str,
    executor_id: str,
    model: str,
    request_payload: object,
    response_payload: object | None,
    status: str,
    started: float,
    error: str | None = None,
) -> None:
    if trace_store is None:
        return
    try:
        request_json, request_preview, request_truncated = _trace_json_and_preview(request_payload)
        response_json = None
        response_preview = None
        response_truncated = False
        if response_payload is not None:
            response_json, response_preview, response_truncated = _trace_json_and_preview(
                response_payload
            )
        metadata = {
            "executor_id": executor_id,
            "model": model,
            "status": status,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        }
        await trace_store.save_agent_call_trace(
            AgentCallTrace(
                id=f"trace-{uuid4().hex}",
                trace_id=trace_id,
                kind="llm",
                title=f"System Planner · {model}",
                request_json=request_json,
                response_json=response_json,
                request_preview=request_preview,
                response_preview=response_preview,
                metadata_json=json.dumps(metadata, ensure_ascii=False, default=str),
                is_truncated=request_truncated or response_truncated,
                created_at=None,
            )
        )
    except Exception:
        logger.debug("Auto-plan trace recording failed", exc_info=True)


def _sanitize_http_error(status_code: int, body: str) -> str:
    """Return a clean error string — strips HTML bodies to avoid leaking page markup."""
    stripped = body.strip()
    if stripped.lower().startswith("<!doctype") or stripped.lower().startswith("<html"):
        return f"HTTP {status_code}: server returned an HTML page (not JSON) — check API endpoint and key"
    return f"HTTP {status_code}: {stripped[:200]}"


def _llm_http_client(timeout_s: float) -> httpx.AsyncClient:
    """Create LLM HTTP clients isolated from local proxy env parsing."""
    return httpx.AsyncClient(timeout=timeout_s, trust_env=False)


def _object_items(value: object) -> list[JsonObject]:
    return [object_dict(item) for item in value] if isinstance(value, list) else []


def extract_tool_use_blocks(message: JsonObject) -> list[JsonObject]:
    """Return valid Anthropic `tool_use` content blocks from a message."""
    tool_uses: list[JsonObject] = []
    for block in _object_items(message.get("content")):
        if block.get("type") != "tool_use":
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


def _resolved_executor(executor: RuntimeExecutorConfig) -> ResolvedRuntimeExecutor | None:
    if not executor.api_endpoint or not executor.api_key:
        return None
    return ResolvedRuntimeExecutor(
        config=executor,
        api_endpoint=executor.api_endpoint,
        api_key=executor.api_key,
    )


def _pick_executor(
    catalog: RuntimeCatalog,
    preferred_id: str | None,
) -> ResolvedRuntimeExecutor | None:
    """Pick a usable executor.

    Order of preference:
      1. The executor whose id matches `preferred_id` (env override).
      2. An executor with `executor_type == "claude"` that is enabled and
         has both api_endpoint + api_key.
      3. Any enabled executor with api_endpoint + api_key.
    """
    if preferred_id:
        for e in catalog.executors:
            if e.id == preferred_id:
                resolved = _resolved_executor(e)
                if resolved is not None:
                    return resolved
                break
    for e in catalog.executors:
        if (
            e.enabled
            and getattr(e, "executor_type", "claude") == "claude"
            and e.api_endpoint
            and e.api_key
        ):
            return _resolved_executor(e)
    for e in catalog.executors:
        if e.enabled and e.api_endpoint and e.api_key:
            return _resolved_executor(e)
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


async def _maybe_await_delta(result: Awaitable[None] | None) -> None:
    if result is not None:
        await result


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _assistant_text(message: JsonObject) -> str:
    text_parts: list[str] = []
    for raw_part in _object_items(message.get("content")):
        part_text = raw_part.get("text")
        if raw_part.get("type") == "text" and isinstance(part_text, str):
            text_parts.append(part_text)
    return "".join(text_parts)


def build_llm_runner(
    catalog_service: RuntimeCatalogService,
    trace_store: AgentCallTraceStore | None = None,
    *,
    timeout_s: float | None = None,
    max_tokens: int | None = None,
    raise_on_max_tokens: bool = False,
) -> LLM_RUNNER_TYPE:
    """Return an async callable that turns a prompt into assistant text."""
    config = _workflow_orchestrator_llm_config()
    request_timeout_s = timeout_s if timeout_s is not None else config.timeout_s
    request_max_tokens = max_tokens if max_tokens is not None else config.max_tokens
    if request_max_tokens < 1:
        raise ValueError("max_tokens must be positive")

    async def runner(prompt: str) -> str | None:
        try:
            catalog = await catalog_service.load_catalog()
            executor = _pick_executor(catalog, config.preferred_executor_id)
            if executor is None:
                logger.info("Auto-plan: no usable executor configured; falling back to heuristic")
                return None
            model = _resolve_model(executor.config, config.preferred_model_id)
            if not model:
                logger.info(
                    "Auto-plan: executor %s has no resolvable model; falling back",
                    executor.config.id,
                )
                return None

            url = llm_api_url(executor.api_endpoint, "/v1/messages")
            # Assistant-prefill: end the messages array with an assistant turn
            # that starts with "{" so the model continues generating from
            # inside an open JSON object — no preamble, no markdown fence, no
            # "Here is the DAG:". The leading "{" is NOT in the model's
            # response, so we prepend it before returning so json.loads sees a
            # complete object.
            prefill_supported = model.casefold() != "minimax-m3"
            primary_messages = [{"role": "user", "content": prompt}]
            if prefill_supported:
                primary_messages.append({"role": "assistant", "content": "{"})
            payload = {
                "model": model,
                "max_tokens": request_max_tokens,
                "messages": primary_messages,
            }
            response_used_prefill = prefill_supported
            trace_id = f"autoplan-{uuid4().hex}"
            # Audit the auto-plan LLM call (PR2): previously this path only
            # emitted WARNING-level stderr and never entered conductor_turns.
            _audit_autoplan(
                "llm_call",
                executor_id=executor.config.id,
                model=model,
                payload={"prompt_chars": len(prompt), "max_tokens": request_max_tokens},
                trace_id=trace_id,
            )
            _call_started = time.monotonic()
            async with _llm_http_client(request_timeout_s) as client:
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
                    executor_id=executor.config.id,
                    model=model,
                    status="error",
                    started=_call_started,
                    payload={"http_status": response.status_code},
                    error=f"HTTP {response.status_code}",
                    trace_id=trace_id,
                )
                await _save_autoplan_trace(
                    trace_store,
                    trace_id=trace_id,
                    executor_id=executor.config.id,
                    model=model,
                    request_payload=payload,
                    response_payload={"http_status": response.status_code, "body": response.text},
                    status="error",
                    started=_call_started,
                    error=f"HTTP {response.status_code}",
                )
                return None
            data = object_dict(response.json())
            if data.get("stop_reason") == "max_tokens":
                logger.warning(
                    "Auto-plan: model output reached max_tokens=%s",
                    request_max_tokens,
                )
                if raise_on_max_tokens:
                    raise LLMOutputTokenLimitError(
                        f"model output reached max_tokens={request_max_tokens}"
                    )
                return None
            if not _assistant_text(data):
                # Retry once without assistant prefill. MiniMax-M3 already uses
                # this shape on the first attempt, so its retry intentionally
                # repeats the compatible request instead of switching to the
                # prefill shape known to produce content=null.
                fallback_payload = {
                    **payload,
                    "messages": [{"role": "user", "content": prompt}],
                }
                async with _llm_http_client(request_timeout_s) as client:
                    fallback_response = await client.post(
                        url,
                        headers={
                            "x-api-key": executor.api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json=fallback_payload,
                    )
                if fallback_response.status_code != 200:
                    logger.warning(
                        "Auto-plan: no-prefill retry returned HTTP %s: %s",
                        fallback_response.status_code,
                        fallback_response.text[:300],
                    )
                    return None
                data = object_dict(fallback_response.json())
                if data.get("stop_reason") == "max_tokens":
                    logger.warning(
                        "Auto-plan: no-prefill retry reached max_tokens=%s",
                        request_max_tokens,
                    )
                    if raise_on_max_tokens:
                        raise LLMOutputTokenLimitError(
                            f"model output reached max_tokens={request_max_tokens}"
                        )
                    return None
                response_used_prefill = False
            _audit_autoplan(
                "llm_return",
                executor_id=executor.config.id,
                model=model,
                status="ok",
                started=_call_started,
                payload={
                    "http_status": response.status_code,
                    "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
                    "stop_reason": data.get("stop_reason"),
                },
                trace_id=trace_id,
            )
            await _save_autoplan_trace(
                trace_store,
                trace_id=trace_id,
                executor_id=executor.config.id,
                model=model,
                request_payload=payload,
                response_payload=data,
                status="ok",
                started=_call_started,
            )
            # Anthropic shape: { "content": [ { "type": "text", "text": "..." }, ... ], ... }
            text = _assistant_text(data)
            if not text:
                return None
            # Prepend the prefilled "{" only when the model continued AFTER it
            # (Anthropic native). Some gateways (MiniMax) ignore the prefill
            # and re-emit "{" themselves; in that case skip the prepend so we
            # don't end up with "{{".
            stripped = text.lstrip()
            if response_used_prefill and not stripped.startswith("{"):
                return "{" + text
            return text
        except LLMOutputTokenLimitError:
            raise
        except httpx.TimeoutException:
            logger.warning("Auto-plan: LLM request timed out after %ss", request_timeout_s)
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


async def call_llm_with_tools(
    *,
    messages: list[JsonObject],
    tools: list[JsonObject],
    ctx: StreamingPlanContext,
) -> JsonObject:
    """Call an Anthropic-compatible messages endpoint with tool definitions."""
    url = llm_api_url(ctx.endpoint, "/v1/messages")
    payload: JsonObject = {
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
    data = object_dict(response.json())
    if extract_tool_use_blocks(data):
        return data
    if not isinstance(data.get("content"), list):
        data["content"] = []
    return data


async def call_llm_with_tools_streaming(
    *,
    messages: list[JsonObject],
    tools: list[JsonObject],
    ctx: StreamingPlanContext,
    on_delta: DeltaCallback | None = None,
    batch_window_ms: int = 100,
) -> JsonObject:
    """Stream an Anthropic-compatible messages response and reconstruct the final message.

    Emits batched `text` and `tool_input_json` deltas through `on_delta`, while
    returning a complete assistant message payload at the end.
    """
    url = llm_api_url(ctx.endpoint, "/v1/messages")
    payload: JsonObject = {
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
    blocks: dict[int, JsonObject] = {}
    pending_chunks: dict[tuple[int, str], str] = {}
    last_flush = time.monotonic()
    stop_reason: str | None = None
    usage: JsonObject | None = None

    async def emit_delta(index: int, kind: str, chunk: str) -> None:
        if not chunk or on_delta is None:
            return
        result = on_delta(index, kind, chunk)
        await _maybe_await_delta(result)

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
                event = parse_json_object(raw)
                if event is None:
                    continue

                etype = event.get("type")
                if etype == "message_start":
                    message = object_dict(event.get("message"))
                    usage_payload = event.get("usage")
                    if isinstance(message.get("usage"), dict):
                        usage = object_dict(message.get("usage"))
                    elif isinstance(usage_payload, dict):
                        usage = object_dict(usage_payload)
                elif etype == "content_block_start":
                    index = _int_value(event.get("index"))
                    content_block = object_dict(event.get("content_block"))
                    block_type = string_value(content_block.get("type"), "text")
                    if index not in blocks:
                        block_order.append(index)
                    if block_type == "tool_use":
                        blocks[index] = {
                            "type": "tool_use",
                            "id": string_value(content_block.get("id")),
                            "name": string_value(content_block.get("name")),
                            "input_json": "",
                        }
                    else:
                        blocks[index] = {
                            "type": "text",
                            "text": string_value(content_block.get("text")),
                        }
                elif etype == "content_block_delta":
                    index = _int_value(event.get("index"))
                    delta = object_dict(event.get("delta"))
                    delta_type = delta.get("type")
                    block = blocks.setdefault(index, {"type": "text", "text": ""})
                    if index not in block_order:
                        block_order.append(index)
                    if delta_type == "text_delta":
                        chunk = string_value(delta.get("text"))
                        if chunk:
                            block["type"] = "text"
                            block["text"] = str(block.get("text") or "") + chunk
                            pending_chunks[(index, "text")] = (
                                pending_chunks.get((index, "text"), "") + chunk
                            )
                    elif delta_type == "input_json_delta":
                        chunk = string_value(delta.get("partial_json"))
                        if chunk:
                            block["type"] = "tool_use"
                            block["input_json"] = str(block.get("input_json") or "") + chunk
                            pending_chunks[(index, "tool_input_json")] = (
                                pending_chunks.get((index, "tool_input_json"), "") + chunk
                            )
                    await flush_pending()
                elif etype == "message_delta":
                    delta = object_dict(event.get("delta"))
                    if delta.get("stop_reason") is not None:
                        stop_reason = str(delta.get("stop_reason"))
                    usage_payload = event.get("usage")
                    if isinstance(usage_payload, dict):
                        usage = object_dict(usage_payload)
                elif etype == "content_block_stop":
                    await flush_pending(force=True)
                elif etype == "message_stop":
                    await flush_pending(force=True)
                    break

    content: list[JsonObject] = []
    for index in sorted(block_order):
        block = blocks.get(index) or {}
        if block.get("type") == "tool_use":
            input_json = str(block.get("input_json") or "").strip()
            tool_input = parse_json_object(input_json) if input_json else {}
            content.append(
                {
                    "type": "tool_use",
                    "id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "input": tool_input or {},
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


def _anthropic_tools_to_openai(tools: list[JsonObject]) -> list[JsonObject]:
    out: list[JsonObject] = []
    for tool in tools:
        name = string_value(tool.get("name"))
        if not name:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": string_value(tool.get("description")),
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
        )
    return out


def _anthropic_messages_to_openai(messages: list[JsonObject]) -> list[JsonObject]:
    """Translate the conductor's Anthropic message list to OpenAI chat messages."""
    out: list[JsonObject] = []
    for msg in messages:
        role = string_value(msg.get("role"))
        content = msg.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            out.append({"role": role, "content": ""})
            continue
        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[JsonObject] = []
            for block in _object_items(content):
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
            assistant_msg: JsonObject = {"role": "assistant"}
            assistant_msg["content"] = "".join(text_parts) or None
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            out.append(assistant_msg)
        else:
            # user turn: may carry tool_result blocks -> one OpenAI "tool" msg each.
            tool_results = [b for b in _object_items(content) if b.get("type") == "tool_result"]
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
                    for b in _object_items(content)
                    if b.get("type") == "text"
                ]
                out.append({"role": "user", "content": "".join(text_parts)})
    return out


def _openai_choice_to_anthropic(
    message: JsonObject, finish_reason: str | None, usage: JsonObject | None
) -> JsonObject:
    content: list[JsonObject] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        content.append({"type": "text", "text": text})
    for tool_call in _object_items(message.get("tool_calls")):
        fn = object_dict(tool_call.get("function"))
        args_raw = fn.get("arguments") or "{}"
        tool_input = (
            parse_json_object(args_raw) if isinstance(args_raw, str) else object_dict(args_raw)
        )
        content.append(
            {
                "type": "tool_use",
                "id": string_value(tool_call.get("id")),
                "name": string_value(fn.get("name")),
                "input": tool_input or {},
            }
        )
    stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
    anthropic_usage: JsonObject = {}
    if usage is not None:
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
    messages: list[JsonObject],
    tools: list[JsonObject],
    ctx: StreamingPlanContext,
) -> JsonObject:
    """Call an OpenAI-compatible /v1/chat/completions endpoint; return Anthropic shape."""
    url = llm_api_url(ctx.endpoint, "/v1/chat/completions")
    payload: JsonObject = {
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
    data = object_dict(response.json())
    raw_choices = data.get("choices")
    choices = raw_choices if isinstance(raw_choices, list) else []
    choice = object_dict(choices[0]) if choices else {}
    return _openai_choice_to_anthropic(
        object_dict(choice.get("message")),
        string_value(choice.get("finish_reason")) or None,
        object_dict(data.get("usage")),
    )


async def call_openai_with_tools_streaming(
    *,
    messages: list[JsonObject],
    tools: list[JsonObject],
    ctx: StreamingPlanContext,
    on_delta: DeltaCallback | None = None,
) -> JsonObject:
    """Stream an OpenAI-compatible chat completion, reconstructing an Anthropic message.

    Emits the same `on_delta(content_block_index, kind, chunk)` contract as the
    Anthropic streamer: text -> kind "text" at block 0; tool-call arguments ->
    kind "tool_input_json" at block (openai_index + 1).
    """
    url = llm_api_url(ctx.endpoint, "/v1/chat/completions")
    payload: JsonObject = {
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
    usage: JsonObject | None = None

    async def emit(block_index: int, kind: str, chunk: str) -> None:
        if not chunk or on_delta is None:
            return
        result = on_delta(block_index, kind, chunk)
        await _maybe_await_delta(result)

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
                event = parse_json_object(raw)
                if event is None:
                    continue
                usage_payload = event.get("usage")
                if isinstance(usage_payload, dict):
                    usage = object_dict(usage_payload)
                raw_choices = event.get("choices")
                choices = raw_choices if isinstance(raw_choices, list) else []
                if not choices:
                    continue
                choice = object_dict(choices[0])
                delta = object_dict(choice.get("delta"))
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason"))
                content_chunk = delta.get("content")
                if isinstance(content_chunk, str) and content_chunk:
                    text_acc += content_chunk
                    await emit(0, "text", content_chunk)
                raw_tool_calls = delta.get("tool_calls")
                tool_calls = raw_tool_calls if isinstance(raw_tool_calls, list) else []
                for raw_tool_call in tool_calls:
                    tc = object_dict(raw_tool_call)
                    idx = _int_value(tc.get("index"))
                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = str(tc["id"])
                    fn = object_dict(tc.get("function"))
                    if fn.get("name"):
                        slot["name"] = str(fn["name"])
                    arg_chunk = fn.get("arguments")
                    if isinstance(arg_chunk, str) and arg_chunk:
                        slot["args"] += arg_chunk
                        await emit(idx + 1, "tool_input_json", arg_chunk)

    content: list[JsonObject] = []
    if text_acc:
        content.append({"type": "text", "text": text_acc})
    for idx in sorted(tool_acc.keys()):
        slot = tool_acc[idx]
        args_str = slot["args"].strip()
        tool_input = parse_json_object(args_str) if args_str else {}
        content.append(
            {
                "type": "tool_use",
                "id": slot["id"],
                "name": slot["name"],
                "input": tool_input or {},
            }
        )
    anthropic_usage: JsonObject = {}
    if usage is not None:
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
