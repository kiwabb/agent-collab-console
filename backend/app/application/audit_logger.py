from __future__ import annotations

"""Compatibility shim — the audit writer moved to `app.application.audit`.

The unified audit trail was refactored into a dedicated `audit/` package so
business modules depend on the `AuditSink` port + the typed recorder facade
instead of importing this writer's global singleton and hand-shaping payloads.

This module is preserved so existing imports keep working:

    from app.application.audit_logger import audit_logger, AuditLogger, ...

New code should import from `app.application.audit` instead. In particular,
tests that `monkeypatch.setattr(audit_logger, "record", ...)` patch the same
singleton instance the recorders resolve via `audit.default_sink()`, so the
shim and the package share one object — patching here is observed there.
"""

from app.application.audit.categories import (  # noqa: F401
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
from app.application.audit.writer import (  # noqa: F401
    AuditLogger,
    _serialize_payload,
    audit_logger,
    default_sink,
)

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
    "AuditLogger",
    "_serialize_payload",
    "audit_logger",
    "default_sink",
]
