"""OpenAI-protocol adapter + Conductor LLM context resolution."""

from __future__ import annotations

import json
from typing import Literal

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
from app.json_safety import JsonObject, object_dict


def _object_list(value: object) -> list[JsonObject]:
    return [object_dict(item) for item in value] if isinstance(value, list) else []


def test_tools_anthropic_to_openai_shape():
    tools: list[JsonObject] = [
        {
            "name": "dispatch_subagent",
            "description": "d",
            "input_schema": {"type": "object", "properties": {"role": {"type": "string"}}},
        }
    ]
    out = _anthropic_tools_to_openai(tools)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "dispatch_subagent",
                "description": "d",
                "parameters": {"type": "object", "properties": {"role": {"type": "string"}}},
            },
        }
    ]


def test_messages_anthropic_to_openai_handles_tool_use_and_tool_result():
    messages: list[JsonObject] = [
        {"role": "user", "content": "do the thing"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll dispatch engineer"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "dispatch_subagent",
                    "input": {"role": "engineer"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": '{"status": "done"}',
                    "is_error": False,
                },
            ],
        },
    ]
    out = _anthropic_messages_to_openai(messages)
    assert out[0] == {"role": "user", "content": "do the thing"}
    # assistant -> content + tool_calls
    assert out[1]["role"] == "assistant"
    assert out[1]["content"] == "I'll dispatch engineer"
    tool_call = object_dict(_object_list(out[1].get("tool_calls"))[0])
    function = object_dict(tool_call.get("function"))
    assert tool_call.get("id") == "call_1"
    assert function.get("name") == "dispatch_subagent"
    assert json.loads(str(function.get("arguments") or "")) == {"role": "engineer"}
    # tool_result -> role "tool"
    assert out[2] == {"role": "tool", "tool_call_id": "call_1", "content": '{"status": "done"}'}


def test_openai_choice_back_to_anthropic():
    message: JsonObject = {
        "role": "assistant",
        "content": "going to engineer",
        "tool_calls": [
            {
                "id": "call_9",
                "type": "function",
                "function": {"name": "dispatch_subagent", "arguments": '{"role": "engineer"}'},
            },
        ],
    }
    out = _openai_choice_to_anthropic(
        message, "tool_calls", {"prompt_tokens": 10, "completion_tokens": 5}
    )
    assert out["stop_reason"] == "tool_use"
    content = _object_list(out.get("content"))
    assert content[0] == {"type": "text", "text": "going to engineer"}
    assert content[1] == {
        "type": "tool_use",
        "id": "call_9",
        "name": "dispatch_subagent",
        "input": {"role": "engineer"},
    }
    assert out["usage"] == {"input_tokens": 10, "output_tokens": 5}


def _catalog(protocol: Literal["anthropic", "openai"]) -> RuntimeCatalog:
    return RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="oai",
                label="OpenAI compat",
                enabled=True,
                executor_type="codex",
                api_endpoint="https://api.example.com",
                api_key="sk-test",
                default_model="gpt-x",
                protocol=protocol,
            )
        ],
        conductor_llm=ConductorLLMConfig(
            executor_id="oai",
            model="gpt-x",
            max_tokens=4321,
            timeout_s=66.0,
        ),
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


def test_invalid_numeric_env_falls_back_to_catalog_config(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LLM_MAX_TOKENS", "not-an-int")
    monkeypatch.setenv("CONDUCTOR_LLM_TIMEOUT", "not-a-float")
    monkeypatch.delenv("CONDUCTOR_LLM_PROTOCOL", raising=False)

    cllm = resolve_conductor_llm_context(_catalog("openai"))

    assert cllm is not None
    assert cllm.ctx.max_tokens == 4321
    assert cllm.ctx.timeout_s == 66.0
