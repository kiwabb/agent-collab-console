from __future__ import annotations

"""Domain ports (hexagonal boundaries).

A *port* is a `typing.Protocol` the domain/application layer depends on, with
the concrete implementation (the *adapter*) supplied from the outside. Keeping
the contract here — not in the module that happens to implement it — lets a
business module declare "I need something that can record audit rows" without
importing the writer, its global singleton, or the `audit_log` table schema.

`AuditSink` is the seam for the unified audit trail. Business code calls a
typed `app.application.audit` recorder, passing a sink that satisfies this
Protocol; production wires the real `AuditLogger` (which implements it), tests
pass a trivial fake that just appends to a list.
"""

from typing import Any, Protocol


class AuditSink(Protocol):
    """A best-effort, fire-and-forget recorder for the unified audit trail.

    The single write contract every audited choke point depends on. The
    keyword-only fields mirror the `AuditLog` row exactly; `category` is the one
    positional argument because every call site always supplies it.

    Implementations MUST be best-effort: `record(...)` never raises into the
    caller (audit logging must not break the thing it audits) and never blocks
    the calling path on I/O.
    """

    def record(
        self,
        category: str,
        *,
        actor: str | None = None,
        issue_id: str | None = None,
        task_id: str | None = None,
        conductor_task_id: str | None = None,
        execution_process_id: str | None = None,
        correlation_id: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
        payload: Any | None = None,
        error: str | None = None,
    ) -> None:
        ...
