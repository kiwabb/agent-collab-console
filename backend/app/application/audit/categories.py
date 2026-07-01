from __future__ import annotations

"""Audit category constants.

The category is a free-form string enum (no DB-level constraint, matching the
PRD). Every audited choke point must use one of these constants rather than a
bare string literal so the set stays closed and greppable. `AUDIT_CATEGORIES`
is the frozenset of all valid values for validation/iteration.
"""

CATEGORY_LLM_CALL = "llm_call"
CATEGORY_LLM_RETURN = "llm_return"
CATEGORY_TOOL_USE = "tool_use"
CATEGORY_TOOL_RESULT = "tool_result"
CATEGORY_COMMAND_EXEC = "command_exec"
CATEGORY_GIT_COMMAND = "git_command"
CATEGORY_CLI_SPAWN = "cli_spawn"
CATEGORY_EVENT = "event"
CATEGORY_AGENT_FINALIZE = "agent_finalize"

AUDIT_CATEGORIES = frozenset(
    {
        CATEGORY_LLM_CALL,
        CATEGORY_LLM_RETURN,
        CATEGORY_TOOL_USE,
        CATEGORY_TOOL_RESULT,
        CATEGORY_COMMAND_EXEC,
        CATEGORY_GIT_COMMAND,
        CATEGORY_CLI_SPAWN,
        CATEGORY_EVENT,
        CATEGORY_AGENT_FINALIZE,
    }
)
