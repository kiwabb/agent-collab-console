from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ExternalAgentKind = Literal["claude_code", "codex"]
ExternalAgentPermission = Literal["prototype:read", "prototype:propose"]
ExternalAgentPairingStatus = Literal["active", "revoked"]
ExternalAgentSubmissionStatus = Literal["processing", "completed", "failed"]
ExternalAgentAuditOutcome = Literal["ok", "error", "denied"]


@dataclass(frozen=True, slots=True)
class ExternalAgentPairingRecord:
    id: str
    client_request_id: str
    project_id: str
    document_id: str
    agent_kind: ExternalAgentKind
    token_digest: str
    permissions: tuple[ExternalAgentPermission, ...]
    status: ExternalAgentPairingStatus
    protocol_version: int
    skill_version: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedExternalAgentPairing:
    pairing: ExternalAgentPairingRecord
    bearer_token: str
    mcp_url: str
    skill_package_path: str
    install_manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class ExternalAgentSubmissionRecord:
    id: str
    pairing_id: str
    client_request_id: str
    request_hash: str
    status: ExternalAgentSubmissionStatus
    proposal_id: str | None
    receipt_json: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExternalAgentSubmissionClaim:
    submission: ExternalAgentSubmissionRecord
    created: bool


@dataclass(frozen=True, slots=True)
class ExternalAgentAuditEvent:
    id: str
    pairing_id: str | None
    project_id: str
    document_id: str
    event_kind: str
    tool_id: str | None
    request_hash: str | None
    outcome: ExternalAgentAuditOutcome
    error_code: str | None
    duration_ms: int | None
    occurred_at: datetime
