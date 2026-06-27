"""Conductor phase state machine.

Extracted from `conductor_main_loop.py` so the transition table + helper
predicates are testable in isolation, and so a future move of the loop
body to its own module has a clean handoff.

Phases:
  awaiting_llm                       - waiting for the LLM turn
  streaming_llm                      - mid-stream LLM response
  dispatching_subagent               - dispatch tool_use to a subagent
  awaiting_subagent                  - waiting for subagent completion
  awaiting_user_clarification        - blocked on user
  paused                             - user/external paused the loop
  done | failed | stalled            - terminal

Per spec (`conductor_state_machine.py` scenarios), an illegal transition
is a conductor_state_violation event + a warning, not a hard raise. The
state machine is therefore a guard, not a control flow construct.
"""

from __future__ import annotations

# Terminal phases: once a conductor reaches one of these its run is over.
# A transition *out* of a terminal phase is a resurrection bug and is blocked
# (GAP C) rather than silently reviving a finished run.
TERMINAL_PHASES: frozenset[str] = frozenset({"done", "failed", "stalled"})

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "awaiting_llm": frozenset(
        {
            "streaming_llm",
            "dispatching_subagent",
            "awaiting_user_clarification",
            "paused",
            "done",
            "failed",
            "stalled",
        }
    ),
    "streaming_llm": frozenset(
        {
            "dispatching_subagent",
            "awaiting_user_clarification",
            "paused",
            "done",
            "failed",
            "stalled",
        }
    ),
    "dispatching_subagent": frozenset(
        {"awaiting_subagent", "awaiting_llm", "paused", "failed", "stalled"}
    ),
    "awaiting_subagent": frozenset({"awaiting_llm", "paused", "failed", "stalled"}),
    "awaiting_user_clarification": frozenset({"awaiting_llm", "paused", "failed", "stalled"}),
    "paused": frozenset(
        {
            "awaiting_llm",
            "streaming_llm",
            "dispatching_subagent",
            "awaiting_subagent",
            "awaiting_user_clarification",
            "done",
            "failed",
            "stalled",
        }
    ),
    "done": frozenset(),
    "failed": frozenset(),
    "stalled": frozenset(),
}


def is_terminal(phase: str | None) -> bool:
    """True if `phase` is a terminal phase (done / failed / stalled)."""
    return phase in TERMINAL_PHASES


def is_legal_transition(from_phase: str | None, to_phase: str | None) -> bool:
    """True if transitioning `from_phase` -> `to_phase` is allowed.

    Unknown source phase => permissive (False) so the caller treats it
    as illegal and emits a `conductor_state_violation` event. This
    matches the spec: any unseen phase is a logging event, not a raise.
    """
    if from_phase is None or to_phase is None:
        return False
    if from_phase not in LEGAL_TRANSITIONS:
        return False
    return to_phase in LEGAL_TRANSITIONS[from_phase]
