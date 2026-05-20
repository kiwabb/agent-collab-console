from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.domain.models import ConductorState


PENDING_ACTIONS = {"dispatch_next", "inject_context"}


def decode_pending_dispatches(state: ConductorState) -> list[dict[str, Any]]:
    try:
        payload = json.loads(state.pending_dispatches_json or "[]")
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def encode_pending_dispatches(dispatches: list[dict[str, Any]]) -> str:
    return json.dumps(dispatches, ensure_ascii=False)


def record_conductor_decision(
    state: ConductorState,
    *,
    decision: dict[str, Any],
    task_id: str,
    completed_node_key: str,
) -> ConductorState:
    """Append a Conductor decision to rolling state and queue executable actions."""
    action = str(decision.get("action") or "proceed")
    thread = _decode_thread(state.running_thread_json)
    thread.append({
        "task_id": task_id,
        "completed_node_key": completed_node_key,
        "action": action,
        "reason": decision.get("reason"),
        "note": decision.get("note"),
        "created_at": datetime.now().isoformat(),
    })

    pending = decode_pending_dispatches(state)
    if action in PENDING_ACTIONS:
        pending.append(_pending_payload(action, decision, task_id, completed_node_key))

    return ConductorState(
        issue_id=state.issue_id,
        running_thread_json=json.dumps(thread, ensure_ascii=False),
        pending_dispatches_json=encode_pending_dispatches(pending),
        scratchpad=str(decision.get("scratchpad") or state.scratchpad or ""),
        decision_count=state.decision_count + 1,
        updated_at=datetime.now(),
    )


def _decode_thread(raw: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _pending_payload(
    action: str,
    decision: dict[str, Any],
    task_id: str,
    completed_node_key: str,
) -> dict[str, Any]:
    payload = {
        "action": action,
        "target_node_key": decision.get("target_node_key"),
        "reason": decision.get("reason"),
        "source_task_id": task_id,
        "source_node_key": completed_node_key,
    }
    if action == "dispatch_next":
        payload["prompt_override"] = decision.get("prompt_override")
        payload["context_inject"] = decision.get("context_inject")
    elif action == "inject_context":
        payload["context_message"] = decision.get("context_message")
    return {key: value for key, value in payload.items() if value is not None}
