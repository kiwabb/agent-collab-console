from datetime import datetime
from pathlib import Path

import asyncio

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.sqlite_store import SQLiteStore
from app.application.conductor_actions import record_conductor_decision
from app.application.conductor_supervisor import ConductorSupervisor
from app.domain.models import ConductorState


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_async_store_persists_conductor_state(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        state = ConductorState(
            issue_id="issue-1",
            running_thread_json='[{"role":"conductor","content":"PM finished"}]',
            pending_dispatches_json='[{"action":"dispatch_next","target_node_key":"architect"}]',
            scratchpad="Architect needs FE boundaries.",
            decision_count=3,
            updated_at=datetime(2026, 5, 20, 12, 0, 0),
        )

        await store.save_conductor_state(state)
        loaded = await store.load_conductor_state("issue-1")
        missing = await store.load_conductor_state("missing")
        await store.close()

        assert loaded == state
        assert missing is None

    import asyncio
    asyncio.run(run())


def test_sync_store_persists_conductor_state(tmp_path: Path):
    store = SQLiteStore(tmp_path / "console.db")
    state = ConductorState(
        issue_id="issue-2",
        running_thread_json="[]",
        pending_dispatches_json="[]",
        scratchpad="",
        decision_count=0,
        updated_at=datetime(2026, 5, 20, 13, 0, 0),
    )

    store.save_conductor_state(state)
    loaded = store.load_conductor_state("issue-2")

    assert loaded == state


def test_record_conductor_decision_appends_thread_and_pending_dispatch():
    state = ConductorState(issue_id="issue-3")

    updated = record_conductor_decision(
        state,
        decision={
            "action": "dispatch_next",
            "reason": "Architect needs to run before QA.",
            "target_node_key": "architect",
            "prompt_override": "Focus on FE boundaries.",
        },
        task_id="task-1",
        completed_node_key="product_manager",
    )

    assert updated.decision_count == 1
    assert '"completed_node_key": "product_manager"' in updated.running_thread_json
    assert '"action": "dispatch_next"' in updated.running_thread_json
    assert '"target_node_key": "architect"' in updated.pending_dispatches_json
    assert '"prompt_override": "Focus on FE boundaries."' in updated.pending_dispatches_json


def test_record_conductor_decision_queues_inject_context():
    state = ConductorState(issue_id="issue-4")

    updated = record_conductor_decision(
        state,
        decision={
            "action": "inject_context",
            "reason": "Architect needs PM constraint.",
            "target_node_key": "architect",
            "context_message": "Preserve the existing API contract.",
        },
        task_id="task-2",
        completed_node_key="product_manager",
    )

    assert '"action": "inject_context"' in updated.pending_dispatches_json
    assert '"context_message": "Preserve the existing API contract."' in updated.pending_dispatches_json


def test_conductor_parser_accepts_phase3_actions():
    dispatch = ConductorSupervisor._parse_decision(
        '{"action":"dispatch_next","reason":"Run security now","target_node_key":"security"}'
    )
    inject = ConductorSupervisor._parse_decision(
        '{"action":"inject_context","reason":"Need context","target_node_key":"architect","context_message":"Keep REST stable"}'
    )

    assert dispatch is not None
    assert dispatch["action"] == "dispatch_next"
    assert inject is not None
    assert inject["action"] == "inject_context"


def test_conductor_state_endpoint_returns_thread_and_pending(client):
    import app.bootstrap as bootstrap_module

    state = ConductorState(
        issue_id="issue-api-state",
        running_thread_json='[{"action":"inject_context","reason":"Need API context"}]',
        pending_dispatches_json='[{"action":"inject_context","target_node_key":"architect"}]',
        scratchpad="Carry API constraints forward.",
        decision_count=2,
        updated_at=datetime(2026, 5, 20, 14, 0, 0),
    )
    _run(bootstrap_module.async_store.save_conductor_state(state))

    response = client.get("/api/codex/issues/issue-api-state/conductor-state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["issue_id"] == "issue-api-state"
    assert payload["decision_count"] == 2
    assert payload["running_thread"][0]["action"] == "inject_context"
    assert payload["pending_dispatches"][0]["target_node_key"] == "architect"
    assert payload["scratchpad"] == "Carry API constraints forward."
