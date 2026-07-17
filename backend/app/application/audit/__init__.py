"""Unified audit-trail package.

Public facade for the audit subsystem. Business modules import from here:

    from app.application import audit
    audit.record_git_command(...)          # typed recorder facade
    audit.CATEGORY_GIT_COMMAND             # category constants

The pieces:
- `categories` — the closed set of audit category string constants.
- `writer`     — the `AuditLogger` adapter (implements `domain.ports.AuditSink`)
                 + the process-wide singleton + `default_sink()`.
- `recorders`  — typed shaping functions, one per audited choke point, each
                 taking an optional injectable `sink: AuditSink`.

Business code depends only on the `AuditSink` Protocol (in `app.domain.ports`)
plus these recorders — never on the writer or its singleton directly.
"""

from __future__ import annotations

from app.application.audit.categories import (
    AUDIT_CATEGORIES,
    CATEGORY_AGENT_FINALIZE,
    CATEGORY_CLI_SPAWN,
    CATEGORY_COMMAND_EXEC,
    CATEGORY_EVENT,
    CATEGORY_GIT_COMMAND,
    CATEGORY_LLM_CALL,
    CATEGORY_LLM_RETURN,
    CATEGORY_TOOL_RESULT,
    CATEGORY_TOOL_USE,
)
from app.application.audit.recorders import (
    CONDUCTOR_TURN_CATEGORY,
    EVENT_SKIP_TYPES,
    McpCallFailureEvidence,
    McpValidationIssueEvidence,
    record_autoplan,
    record_cli_spawn,
    record_command_execs,
    record_conductor_turn,
    record_event,
    record_git_command,
    record_mcp_call,
)
from app.application.audit.writer import AuditLogger, _serialize_payload, audit_logger, default_sink

__all__ = [
    "AUDIT_CATEGORIES",
    "CATEGORY_AGENT_FINALIZE",
    "CATEGORY_CLI_SPAWN",
    "CATEGORY_COMMAND_EXEC",
    "CATEGORY_EVENT",
    "CATEGORY_GIT_COMMAND",
    "CATEGORY_LLM_CALL",
    "CATEGORY_LLM_RETURN",
    "CATEGORY_TOOL_RESULT",
    "CATEGORY_TOOL_USE",
    "CONDUCTOR_TURN_CATEGORY",
    "EVENT_SKIP_TYPES",
    "AuditLogger",
    "McpCallFailureEvidence",
    "McpValidationIssueEvidence",
    "_serialize_payload",
    "audit_logger",
    "default_sink",
    "record_autoplan",
    "record_cli_spawn",
    "record_command_execs",
    "record_conductor_turn",
    "record_event",
    "record_git_command",
    "record_mcp_call",
]
