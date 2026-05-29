import asyncio

import pytest

from app.application.conductor_main_loop import (
    _run_heartbeat_pulse,
    conductor_language_directive,
    detect_text_language,
    run_conductor_loop,
)
from app.application.conductor_tools import build_conductor_tools
from app.application.llm_runner import extract_tool_use_blocks
from app.domain.models import ProjectMemoryEmbedding


def test_conductor_language_directive_auto_is_empty():
    """'auto' (default) keeps the legacy match-the-issue behavior: no directive."""
    assert conductor_language_directive("auto") == ""
    assert conductor_language_directive("") == ""
    assert conductor_language_directive(None) == ""


def test_conductor_language_directive_forces_locale():
    """A concrete locale injects a non-empty, locale-appropriate directive."""
    zh = conductor_language_directive("zh-CN")
    assert "简体中文" in zh
    en = conductor_language_directive("en-US")
    assert "English" in en
    # Unknown locale codes still produce a directive referencing the code.
    other = conductor_language_directive("fr-FR")
    assert "fr-FR" in other


def test_detect_text_language_matches_issue_language():
    """'auto' resolution: CJK content => zh, otherwise en. This is what un-froze
    the conductor's English narration on Chinese issues when output_language is
    unset/auto."""
    assert detect_text_language("为 backend 添加 GET /api/codex/echo 端点", None) == "zh"
    assert detect_text_language("Add GET /api/codex/echo endpoint", None) == "en"
    # Description carries the language even when the title is English.
    assert detect_text_language("Add endpoint", "需要返回时间戳") == "zh"
    assert detect_text_language("", None) == "en"
    # A concrete zh locale produced by auto-resolution drives a Chinese directive.
    assert "简体中文" in conductor_language_directive(
        detect_text_language("为 backend 添加端点", None)
    )


@pytest.mark.asyncio
async def test_heartbeat_pulse_survives_transient_failures_and_alerts():
    """GAP A: a failing heartbeat must not kill the pulse; it alerts after N."""
    beats = {"ok": 0, "fail": 0}
    degraded: list[tuple[int, str]] = []

    async def heartbeat():
        # Fail the first 3 renewals, then recover.
        if beats["ok"] + beats["fail"] < 3:
            beats["fail"] += 1
            raise RuntimeError("db unavailable")
        beats["ok"] += 1

    async def on_degraded(n, exc):
        degraded.append((n, str(exc)))

    pulse = asyncio.create_task(
        _run_heartbeat_pulse(heartbeat, 0.0, on_degraded=on_degraded, alert_after=3)
    )
    # Let the pulse run several iterations, then stop it.
    for _ in range(200):
        if beats["ok"] >= 2 and degraded:
            break
        await asyncio.sleep(0)
    pulse.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pulse

    # Loop survived the 3 failures and went on to renew successfully.
    assert beats["fail"] == 3
    assert beats["ok"] >= 1
    # Degraded callback fired exactly once, at the 3rd consecutive failure.
    assert len(degraded) == 1
    assert degraded[0][0] == 3


@pytest.mark.asyncio
async def test_heartbeat_pulse_propagates_cancellation():
    """Cancellation must tear the pulse down cleanly (not be swallowed)."""
    async def heartbeat():
        return None

    pulse = asyncio.create_task(_run_heartbeat_pulse(heartbeat, 0.0))
    await asyncio.sleep(0)
    pulse.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pulse


@pytest.mark.asyncio
async def test_conductor_loop_executes_tool_use_and_feeds_tool_result_back():
    calls = []

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_memory",
                        "name": "retrieve_cold_memory",
                        "input": {"query": "auth token"},
                    }
                ],
            }
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"][0]["type"] == "tool_result"
        assert messages[-1]["content"][0]["tool_use_id"] == "toolu_memory"
        assert "auth token regression" in messages[-1]["content"][0]["content"]
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Use the auth token regression memory."}],
        }

    async def retrieve_cold_memory(tool_input):
        assert tool_input == {"query": "auth token"}
        return {"memories": ["auth token regression happened in refresh flow"]}

    result = await run_conductor_loop(
        prompt="Plan the auth fix.",
        llm=fake_llm,
        tools={"retrieve_cold_memory": retrieve_cold_memory},
        tool_definitions=[{"name": "retrieve_cold_memory"}],
    )

    assert result.final_text == "Use the auth token regression memory."
    assert len(result.tool_events) == 1
    assert result.tool_events[0]["name"] == "retrieve_cold_memory"
    assert calls[1][-1]["content"][0]["tool_use_id"] == "toolu_memory"


@pytest.mark.asyncio
async def test_conductor_loop_stops_when_finalize_task_tool_returns_answer():
    async def fake_llm(messages, tools):
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"answer": "done with confidence", "status": "done"},
                }
            ],
        }

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Finish the review.",
        llm=fake_llm,
        tools={"finalize_task": finalize_task},
        tool_definitions=[{"name": "finalize_task"}],
    )

    assert result.status == "done"
    assert result.final_text == "done with confidence"
    assert result.turn_count == 1


@pytest.mark.asyncio
async def test_conductor_loop_records_turn_timeline():
    recorded = []

    async def fake_llm(messages, tools):
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"answer": "captured", "status": "done"},
                }
            ],
        }

    async def finalize_task(tool_input):
        return tool_input

    await run_conductor_loop(
        prompt="Record turns.",
        llm=fake_llm,
        tools={"finalize_task": finalize_task},
        tool_definitions=[{"name": "finalize_task"}],
        turn_recorder=lambda **turn: recorded.append((turn["kind"], turn["turn_index"], turn["sub_index"])),
    )

    assert recorded == [
        ("llm_request", 0, 0),
        ("llm_response", 0, 0),
        ("tool_use", 0, 1),
        ("tool_result", 0, 1),
        ("finalize", 0, 1),
    ]


@pytest.mark.asyncio
async def test_conductor_loop_passes_token_delta_callback_to_llm():
    deltas = []

    async def fake_llm(messages, tools, on_token_delta=None):
        assert on_token_delta is not None
        await on_token_delta(
            turn_index=0,
            sub_index=0,
            content_block_index=0,
            kind="text",
            chunk="hello",
        )
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"output_tokens": 1},
        }

    async def capture_delta(**payload):
        deltas.append(payload)

    result = await run_conductor_loop(
        prompt="Stream a token.",
        llm=fake_llm,
        tools={},
        tool_definitions=[],
        on_token_delta=capture_delta,
    )

    assert result.status == "done"
    assert deltas == [
        {
            "turn_index": 0,
            "sub_index": 0,
            "content_block_index": 0,
            "kind": "text",
            "chunk": "hello",
        }
    ]


@pytest.mark.asyncio
async def test_conductor_loop_injects_user_interjection_before_next_llm_call():
    calls = []
    pending_inbox = [["skip architect, go straight to engineer"], []]

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_memory",
                        "name": "retrieve_cold_memory",
                        "input": {"query": "plan"},
                    }
                ],
            }
        assert any(
            entry.get("role") == "user"
            and entry.get("content") == "[USER INTERJECTION] skip architect, go straight to engineer"
            for entry in messages
        )
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Skipping architect."}],
        }

    async def retrieve_cold_memory(tool_input):
        return {"memories": ["plan"]}  # pragma: no cover - value asserted through flow

    async def drain_inbox():
        return pending_inbox.pop(0) if pending_inbox else []

    result = await run_conductor_loop(
        prompt="Plan this issue.",
        llm=fake_llm,
        tools={"retrieve_cold_memory": retrieve_cold_memory},
        tool_definitions=[{"name": "retrieve_cold_memory"}],
        inbox_drain=drain_inbox,
    )

    assert result.status == "done"
    assert result.final_text == "Skipping architect."


@pytest.mark.asyncio
async def test_conductor_loop_runs_multiple_tool_uses_in_one_turn_concurrently():
    """A single turn that emits several tool_use blocks executes them in parallel
    (overlapping in time) and feeds back tool_results in the original order."""
    running = 0
    max_concurrent = 0

    async def slow_dispatch(tool_input):
        nonlocal running, max_concurrent
        running += 1
        max_concurrent = max(max_concurrent, running)
        try:
            await asyncio.sleep(0.05)
            return {"role": tool_input.get("role"), "status": "done"}
        finally:
            running -= 1

    calls = []

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "dispatch_subagent", "input": {"role": "reviewer_a"}},
                    {"type": "tool_use", "id": "t2", "name": "dispatch_subagent", "input": {"role": "reviewer_b"}},
                    {"type": "tool_use", "id": "t3", "name": "dispatch_subagent", "input": {"role": "reviewer_c"}},
                ],
            }
        # tool_results must come back aligned with the original tool_use ids/order.
        blocks = messages[-1]["content"]
        assert [b["tool_use_id"] for b in blocks] == ["t1", "t2", "t3"]
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "all reviewed"}]}

    result = await run_conductor_loop(
        prompt="Review from three angles.",
        llm=fake_llm,
        tools={"dispatch_subagent": slow_dispatch},
        tool_definitions=[{"name": "dispatch_subagent"}],
    )

    assert result.final_text == "all reviewed"
    assert len(result.tool_events) == 3
    # If execution were serial, max_concurrent would be 1. Parallel => 3.
    assert max_concurrent == 3


@pytest.mark.asyncio
async def test_conductor_loop_seals_max_wall_when_wall_clock_exceeded():
    """The whole-loop wall-clock ceiling stops a loop that never finalizes, even
    if it is still under max_turns."""
    async def fake_llm(messages, tools):
        # Always asks for more work; would loop until max_turns without the ceiling.
        return {
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": "tx", "name": "dispatch_subagent", "input": {"role": "engineer"}}
            ],
        }

    async def dispatch(tool_input):
        await asyncio.sleep(0.03)
        return {"status": "done"}

    result = await run_conductor_loop(
        prompt="Never-ending work.",
        llm=fake_llm,
        tools={"dispatch_subagent": dispatch},
        tool_definitions=[{"name": "dispatch_subagent"}],
        max_turns=50,
        max_wall_s=0.05,
    )

    assert result.status == "max_wall"
    assert result.turn_count < 50


@pytest.mark.asyncio
async def test_conductor_loop_wall_clock_disabled_when_zero():
    """max_wall_s=0 disables the ceiling; the loop runs to its natural finalize."""
    async def fake_llm(messages, tools):
        return {
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": "f", "name": "finalize_task", "input": {"status": "done", "answer": "ok"}}
            ],
        }

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Quick.",
        llm=fake_llm,
        tools={"finalize_task": finalize_task},
        tool_definitions=[{"name": "finalize_task"}],
        max_wall_s=0,
    )
    assert result.status == "done"


@pytest.mark.asyncio
async def test_conductor_tools_expose_phase6_tool_schema_and_memory_lookup(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store.save_project_memory_embedding(
        ProjectMemoryEmbedding(
            id="mem-1",
            project_id="project-1",
            source_kind="warm_summary",
            source_id="sum-1",
            summary_text="auth token regression happened in refresh flow",
        )
    )

    registry = build_conductor_tools(project_id="project-1", store=store)
    await store.close()

    names = {tool["name"] for tool in registry.definitions}
    assert names == {
        "retrieve_cold_memory",
        "dispatch_subagent",
        "spawn_custom_subagent",
        "inject_context_into_node",
        "request_user_clarification",
        "finalize_task",
    }
    memory = await registry.tools["retrieve_cold_memory"]({"query": "auth token", "top_k": 2})
    assert memory["memories"] == ["auth token regression happened in refresh flow"]


def test_llm_runner_extracts_anthropic_tool_use_blocks():
    response = {
        "content": [
            {"type": "text", "text": "I need memory."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "retrieve_cold_memory",
                "input": {"query": "auth"},
            },
            {"type": "tool_use", "id": "toolu_bad", "name": "", "input": "bad"},
        ]
    }

    assert extract_tool_use_blocks(response) == [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "retrieve_cold_memory",
            "input": {"query": "auth"},
        }
    ]
