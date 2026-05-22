import pytest

from app.application.conductor_main_loop import run_conductor_loop
from app.application.conductor_tools import build_conductor_tools
from app.application.llm_runner import extract_tool_use_blocks
from app.domain.models import ProjectMemoryEmbedding


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
