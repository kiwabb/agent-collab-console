"""OpenAI-protocol adapter + Conductor LLM context resolution."""
from __future__ import annotations

import json

from app.application.conductor_llm import resolve_conductor_llm_context
from app.application.llm_runner import (
    _anthropic_messages_to_openai,
    _anthropic_tools_to_openai,
    _openai_choice_to_anthropic,
)
from app.domain.models import (
    ConductorLLMConfig,
    RuntimeCatalog,
    RuntimeExecutorConfig,
)


def test_tools_anthropic_to_openai_shape():
    tools = [{"name": "dispatch_subagent", "description": "d", "input_schema": {"type": "object", "properties": {"role": {"type": "string"}}}}]
    out = _anthropic_tools_to_openai(tools)
    assert out == [{
        "type": "function",
        "function": {
            "name": "dispatch_subagent",
            "description": "d",
            "parameters": {"type": "object", "properties": {"role": {"type": "string"}}},
        },
    }]


def test_messages_anthropic_to_openai_handles_tool_use_and_tool_result():
    messages = [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "I'll dispatch engineer"},
            {"type": "tool_use", "id": "call_1", "name": "dispatch_subagent", "input": {"role": "engineer"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "{\"status\": \"done\"}", "is_error": False},
        ]},
    ]
    out = _anthropic_messages_to_openai(messages)
    assert out[0] == {"role": "user", "content": "do the thing"}
    # assistant -> content + tool_calls
    assert out[1]["role"] == "assistant"
    assert out[1]["content"] == "I'll dispatch engineer"
    assert out[1]["tool_calls"][0]["id"] == "call_1"
    assert out[1]["tool_calls"][0]["function"]["name"] == "dispatch_subagent"
    assert json.loads(out[1]["tool_calls"][0]["function"]["arguments"]) == {"role": "engineer"}
    # tool_result -> role "tool"
    assert out[2] == {"role": "tool", "tool_call_id": "call_1", "content": "{\"status\": \"done\"}"}


def test_openai_choice_back_to_anthropic():
    message = {
        "role": "assistant",
        "content": "going to engineer",
        "tool_calls": [
            {"id": "call_9", "type": "function", "function": {"name": "dispatch_subagent", "arguments": "{\"role\": \"engineer\"}"}},
        ],
    }
    out = _openai_choice_to_anthropic(message, "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5})
    assert out["stop_reason"] == "tool_use"
    assert out["content"][0] == {"type": "text", "text": "going to engineer"}
    assert out["content"][1] == {"type": "tool_use", "id": "call_9", "name": "dispatch_subagent", "input": {"role": "engineer"}}
    assert out["usage"] == {"input_tokens": 10, "output_tokens": 5}


def _catalog(protocol: str) -> RuntimeCatalog:
    return RuntimeCatalog(
        executors=[RuntimeExecutorConfig(
            id="oai", label="OpenAI compat", enabled=True, executor_type="codex",
            api_endpoint="https://api.example.com", api_key="sk-test",
            default_model="gpt-x", protocol=protocol,
        )],
        conductor_llm=ConductorLLMConfig(executor_id="oai", model="gpt-x"),
    )


def test_resolve_conductor_llm_context_picks_openai_protocol(monkeypatch):
    monkeypatch.delenv("CONDUCTOR_LLM_PROTOCOL", raising=False)
    monkeypatch.delenv("CONDUCTOR_LLM_EXECUTOR_ID", raising=False)
    monkeypatch.delenv("CONDUCTOR_LLM_MODEL", raising=False)
    cllm = resolve_conductor_llm_context(_catalog("openai"))
    assert cllm is not None
    assert cllm.protocol == "openai"
    assert cllm.ctx.endpoint == "https://api.example.com"
    assert cllm.ctx.model == "gpt-x"


def test_resolve_conductor_llm_context_defaults_anthropic(monkeypatch):
    monkeypatch.delenv("CONDUCTOR_LLM_PROTOCOL", raising=False)
    monkeypatch.delenv("CONDUCTOR_LLM_EXECUTOR_ID", raising=False)
    cllm = resolve_conductor_llm_context(_catalog("anthropic"))
    assert cllm is not None
    assert cllm.protocol == "anthropic"


def test_env_overrides_protocol(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LLM_PROTOCOL", "openai")
    monkeypatch.delenv("CONDUCTOR_LLM_EXECUTOR_ID", raising=False)
    cllm = resolve_conductor_llm_context(_catalog("anthropic"))
    assert cllm is not None
    assert cllm.protocol == "openai"  # env wins over executor field
