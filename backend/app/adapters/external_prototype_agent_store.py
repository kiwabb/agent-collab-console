from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import NoReturn, cast

import aiosqlite

from app.application.external_prototype_agent_contracts import (
    EXTERNAL_AGENT_PROTOCOL_VERSION,
    PROTOTYPE_DESIGNER_SKILL_VERSION,
    SHA256_PATTERN,
)
from app.application.external_prototype_agent_service import ExternalPrototypeAgentError
from app.domain.external_prototype_agent import (
    ExternalAgentAuditEvent,
    ExternalAgentAuditOutcome,
    ExternalAgentKind,
    ExternalAgentPairingRecord,
    ExternalAgentPairingStatus,
    ExternalAgentPermission,
    ExternalAgentSubmissionClaim,
    ExternalAgentSubmissionRecord,
    ExternalAgentSubmissionStatus,
)

PAIRING_COLUMNS = """
    id, client_request_id, project_id, document_id, agent_kind,
    token_digest, permissions_json, status, protocol_version, skill_version,
    created_at, expires_at, revoked_at, last_used_at
"""
SUBMISSION_COLUMNS = """
    id, pairing_id, client_request_id, request_hash, status, proposal_id,
    receipt_json, error_code, created_at, updated_at, completed_at
"""
AUDIT_COLUMNS = """
    id, pairing_id, project_id, document_id, event_kind, tool_id,
    request_hash, outcome, error_code, duration_ms, occurred_at
"""


class AsyncExternalPrototypeAgentStore:
    """SQLite persistence for external Agent capabilities and safe audit metadata."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = db_path
        self._connection: aiosqlite.Connection | None = None
        self._connection_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        async with self._operation_lock:
            if self._initialized:
                return
            connection = await self._get_connection()
            await connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS external_prototype_agent_pairings (
                    id TEXT PRIMARY KEY,
                    client_request_id TEXT NOT NULL UNIQUE,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    agent_kind TEXT NOT NULL CHECK (agent_kind IN ('claude_code', 'codex')),
                    token_digest TEXT NOT NULL UNIQUE,
                    permissions_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
                    protocol_version INTEGER NOT NULL,
                    skill_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    last_used_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_external_agent_pairing_scope
                    ON external_prototype_agent_pairings(project_id, document_id, status);
                CREATE INDEX IF NOT EXISTS idx_external_agent_pairing_expiry
                    ON external_prototype_agent_pairings(expires_at);

                CREATE TABLE IF NOT EXISTS external_prototype_agent_submissions (
                    id TEXT PRIMARY KEY,
                    pairing_id TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
                    proposal_id TEXT,
                    receipt_json TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(pairing_id, client_request_id),
                    FOREIGN KEY (pairing_id) REFERENCES external_prototype_agent_pairings(id)
                );

                CREATE INDEX IF NOT EXISTS idx_external_agent_submission_proposal
                    ON external_prototype_agent_submissions(proposal_id);

                CREATE TABLE IF NOT EXISTS external_prototype_agent_audit_events (
                    id TEXT PRIMARY KEY,
                    pairing_id TEXT,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    tool_id TEXT,
                    request_hash TEXT,
                    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'error', 'denied')),
                    error_code TEXT,
                    duration_ms INTEGER,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY (pairing_id) REFERENCES external_prototype_agent_pairings(id)
                );

                CREATE INDEX IF NOT EXISTS idx_external_agent_audit_scope_time
                    ON external_prototype_agent_audit_events(
                        project_id, document_id, occurred_at
                    );
                """
            )
            await connection.commit()
            self._initialized = True

    async def close(self) -> None:
        async with self._connection_lock:
            if self._connection is not None:
                await self._connection.close()
                self._connection = None
            self._initialized = False

    async def create_pairing(
        self,
        pairing: ExternalAgentPairingRecord,
        event: ExternalAgentAuditEvent,
    ) -> ExternalAgentPairingRecord:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            await connection.execute("BEGIN IMMEDIATE")
            try:
                existing = await self._fetch_pairing_by_client_request_id(
                    connection,
                    pairing.client_request_id,
                )
                if existing is not None:
                    await connection.commit()
                    return existing
                await connection.execute(
                    """
                    INSERT INTO external_prototype_agent_pairings (
                        id, client_request_id, project_id, document_id, agent_kind,
                        token_digest, permissions_json, status, protocol_version,
                        skill_version, created_at, expires_at, revoked_at, last_used_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._pairing_values(pairing),
                )
                await self._insert_audit_event(connection, event)
                await connection.commit()
                return pairing
            except BaseException:
                # Transaction boundaries must roll back on DB errors and task cancellation.
                await connection.rollback()
                raise

    async def load_pairing_by_token_digest(
        self,
        token_digest: str,
    ) -> ExternalAgentPairingRecord | None:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            cursor = await connection.execute(
                f"""
                SELECT {PAIRING_COLUMNS}
                FROM external_prototype_agent_pairings WHERE token_digest = ?
                """,
                (token_digest,),
            )
            return self._pairing_from_row(await cursor.fetchone())

    async def load_pairing(self, pairing_id: str) -> ExternalAgentPairingRecord | None:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            cursor = await connection.execute(
                f"""
                SELECT {PAIRING_COLUMNS}
                FROM external_prototype_agent_pairings WHERE id = ?
                """,
                (pairing_id,),
            )
            return self._pairing_from_row(await cursor.fetchone())

    async def revoke_pairing(
        self,
        pairing: ExternalAgentPairingRecord,
        event: ExternalAgentAuditEvent,
    ) -> None:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    """
                    UPDATE external_prototype_agent_pairings
                    SET status = ?, revoked_at = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (
                        pairing.status,
                        self._datetime_value(pairing.revoked_at),
                        pairing.id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExternalPrototypeAgentError(
                        "pairing_state_conflict",
                        "external Agent pairing state changed before revocation",
                    )
                await self._insert_audit_event(connection, event)
                await connection.commit()
            except BaseException:
                # Transaction boundaries must roll back on DB errors and task cancellation.
                await connection.rollback()
                raise

    async def touch_pairing(self, pairing_id: str, used_at: datetime) -> None:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            cursor = await connection.execute(
                """
                UPDATE external_prototype_agent_pairings
                SET last_used_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (used_at.isoformat(), pairing_id),
            )
            if cursor.rowcount != 1:
                await connection.rollback()
                raise ExternalPrototypeAgentError(
                    "pairing_state_conflict",
                    "external Agent pairing state changed during authorization",
                )
            await connection.commit()

    async def claim_submission(
        self,
        submission: ExternalAgentSubmissionRecord,
    ) -> ExternalAgentSubmissionClaim:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    f"""
                    SELECT {SUBMISSION_COLUMNS}
                    FROM external_prototype_agent_submissions
                    WHERE pairing_id = ? AND client_request_id = ?
                    """,
                    (submission.pairing_id, submission.client_request_id),
                )
                existing_row = await cursor.fetchone()
                if existing_row is not None:
                    existing = self._submission_from_row(existing_row)
                    if existing.request_hash != submission.request_hash:
                        raise ExternalPrototypeAgentError(
                            "submission_conflict",
                            "proposal request identity was reused with different arguments",
                        )
                    await connection.commit()
                    return ExternalAgentSubmissionClaim(submission=existing, created=False)
                await connection.execute(
                    """
                    INSERT INTO external_prototype_agent_submissions (
                        id, pairing_id, client_request_id, request_hash, status,
                        proposal_id, receipt_json, error_code, created_at, updated_at,
                        completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._submission_values(submission),
                )
                await connection.commit()
                return ExternalAgentSubmissionClaim(submission=submission, created=True)
            except BaseException:
                # Transaction boundaries must roll back on DB errors and task cancellation.
                await connection.rollback()
                raise

    async def complete_submission(
        self,
        submission: ExternalAgentSubmissionRecord,
        event: ExternalAgentAuditEvent,
    ) -> None:
        await self._finish_submission(submission, event)

    async def fail_submission(
        self,
        submission: ExternalAgentSubmissionRecord,
        event: ExternalAgentAuditEvent,
    ) -> None:
        await self._finish_submission(submission, event)

    async def record_audit_event(self, event: ExternalAgentAuditEvent) -> None:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            await self._insert_audit_event(connection, event)
            await connection.commit()

    async def list_audit_events(
        self,
        project_id: str,
        document_id: str,
        *,
        limit: int,
    ) -> list[ExternalAgentAuditEvent]:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            cursor = await connection.execute(
                f"""
                SELECT {AUDIT_COLUMNS}
                FROM external_prototype_agent_audit_events
                WHERE project_id = ? AND document_id = ?
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (project_id, document_id, limit),
            )
            rows = await cursor.fetchall()
            return [self._audit_from_row(row) for row in rows]

    async def _finish_submission(
        self,
        submission: ExternalAgentSubmissionRecord,
        event: ExternalAgentAuditEvent,
    ) -> None:
        await self.initialize()
        async with self._operation_lock:
            connection = await self._get_connection()
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    """
                    UPDATE external_prototype_agent_submissions
                    SET status = ?, proposal_id = ?, receipt_json = ?, error_code = ?,
                        updated_at = ?, completed_at = ?
                    WHERE id = ? AND request_hash = ? AND status = 'processing'
                    """,
                    (
                        submission.status,
                        submission.proposal_id,
                        submission.receipt_json,
                        submission.error_code,
                        submission.updated_at.isoformat(),
                        self._datetime_value(submission.completed_at),
                        submission.id,
                        submission.request_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExternalPrototypeAgentError(
                        "submission_state_conflict",
                        "proposal submission state changed before completion",
                    )
                await self._insert_audit_event(connection, event)
                await connection.commit()
            except BaseException:
                # Transaction boundaries must roll back on DB errors and task cancellation.
                await connection.rollback()
                raise

    async def _get_connection(self) -> aiosqlite.Connection:
        async with self._connection_lock:
            if self._connection is None:
                self._connection = await aiosqlite.connect(self._db_path, timeout=30.0)
                self._connection.row_factory = aiosqlite.Row
                await self._connection.execute("PRAGMA journal_mode=WAL")
                await self._connection.execute("PRAGMA synchronous=NORMAL")
                await self._connection.execute("PRAGMA foreign_keys=ON")
            return self._connection

    @staticmethod
    async def _fetch_pairing_by_client_request_id(
        connection: aiosqlite.Connection,
        client_request_id: str,
    ) -> ExternalAgentPairingRecord | None:
        cursor = await connection.execute(
            f"""
            SELECT {PAIRING_COLUMNS}
            FROM external_prototype_agent_pairings WHERE client_request_id = ?
            """,
            (client_request_id,),
        )
        return AsyncExternalPrototypeAgentStore._pairing_from_row(await cursor.fetchone())

    @staticmethod
    async def _insert_audit_event(
        connection: aiosqlite.Connection,
        event: ExternalAgentAuditEvent,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO external_prototype_agent_audit_events (
                id, pairing_id, project_id, document_id, event_kind, tool_id,
                request_hash, outcome, error_code, duration_ms, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.pairing_id,
                event.project_id,
                event.document_id,
                event.event_kind,
                event.tool_id,
                event.request_hash,
                event.outcome,
                event.error_code,
                event.duration_ms,
                event.occurred_at.isoformat(),
            ),
        )

    @staticmethod
    def _pairing_values(pairing: ExternalAgentPairingRecord) -> tuple[object, ...]:
        return (
            pairing.id,
            pairing.client_request_id,
            pairing.project_id,
            pairing.document_id,
            pairing.agent_kind,
            pairing.token_digest,
            json.dumps(pairing.permissions, separators=(",", ":")),
            pairing.status,
            pairing.protocol_version,
            pairing.skill_version,
            pairing.created_at.isoformat(),
            pairing.expires_at.isoformat(),
            AsyncExternalPrototypeAgentStore._datetime_value(pairing.revoked_at),
            AsyncExternalPrototypeAgentStore._datetime_value(pairing.last_used_at),
        )

    @staticmethod
    def _submission_values(submission: ExternalAgentSubmissionRecord) -> tuple[object, ...]:
        return (
            submission.id,
            submission.pairing_id,
            submission.client_request_id,
            submission.request_hash,
            submission.status,
            submission.proposal_id,
            submission.receipt_json,
            submission.error_code,
            submission.created_at.isoformat(),
            submission.updated_at.isoformat(),
            AsyncExternalPrototypeAgentStore._datetime_value(submission.completed_at),
        )

    @staticmethod
    def _pairing_from_row(row: aiosqlite.Row | None) -> ExternalAgentPairingRecord | None:
        if row is None:
            return None
        permissions = AsyncExternalPrototypeAgentStore._permissions(row["permissions_json"])
        pairing = ExternalAgentPairingRecord(
            id=AsyncExternalPrototypeAgentStore._string(row["id"], "id"),
            client_request_id=AsyncExternalPrototypeAgentStore._string(
                row["client_request_id"], "client_request_id"
            ),
            project_id=AsyncExternalPrototypeAgentStore._string(row["project_id"], "project_id"),
            document_id=AsyncExternalPrototypeAgentStore._string(
                row["document_id"], "document_id"
            ),
            agent_kind=AsyncExternalPrototypeAgentStore._agent_kind(row["agent_kind"]),
            token_digest=AsyncExternalPrototypeAgentStore._string(
                row["token_digest"], "token_digest"
            ),
            permissions=permissions,
            status=AsyncExternalPrototypeAgentStore._pairing_status(row["status"]),
            protocol_version=AsyncExternalPrototypeAgentStore._integer(
                row["protocol_version"], "protocol_version"
            ),
            skill_version=AsyncExternalPrototypeAgentStore._string(
                row["skill_version"], "skill_version"
            ),
            created_at=AsyncExternalPrototypeAgentStore._datetime(row["created_at"], "created_at"),
            expires_at=AsyncExternalPrototypeAgentStore._datetime(row["expires_at"], "expires_at"),
            revoked_at=AsyncExternalPrototypeAgentStore._optional_datetime(
                row["revoked_at"], "revoked_at"
            ),
            last_used_at=AsyncExternalPrototypeAgentStore._optional_datetime(
                row["last_used_at"], "last_used_at"
            ),
        )
        if (
            SHA256_PATTERN.fullmatch(pairing.token_digest) is None
            or pairing.protocol_version != EXTERNAL_AGENT_PROTOCOL_VERSION
            or pairing.skill_version != PROTOTYPE_DESIGNER_SKILL_VERSION
            or pairing.expires_at <= pairing.created_at
            or (pairing.status == "active" and pairing.revoked_at is not None)
            or (pairing.status == "revoked" and pairing.revoked_at is None)
            or (
                pairing.last_used_at is not None
                and pairing.last_used_at < pairing.created_at
            )
        ):
            AsyncExternalPrototypeAgentStore._invalid_record("pairing lifecycle")
        return pairing

    @staticmethod
    def _submission_from_row(row: aiosqlite.Row) -> ExternalAgentSubmissionRecord:
        return ExternalAgentSubmissionRecord(
            id=AsyncExternalPrototypeAgentStore._string(row["id"], "id"),
            pairing_id=AsyncExternalPrototypeAgentStore._string(row["pairing_id"], "pairing_id"),
            client_request_id=AsyncExternalPrototypeAgentStore._string(
                row["client_request_id"], "client_request_id"
            ),
            request_hash=AsyncExternalPrototypeAgentStore._string(
                row["request_hash"], "request_hash"
            ),
            status=AsyncExternalPrototypeAgentStore._submission_status(row["status"]),
            proposal_id=AsyncExternalPrototypeAgentStore._optional_string(
                row["proposal_id"], "proposal_id"
            ),
            receipt_json=AsyncExternalPrototypeAgentStore._optional_string(
                row["receipt_json"], "receipt_json"
            ),
            error_code=AsyncExternalPrototypeAgentStore._optional_string(
                row["error_code"], "error_code"
            ),
            created_at=AsyncExternalPrototypeAgentStore._datetime(row["created_at"], "created_at"),
            updated_at=AsyncExternalPrototypeAgentStore._datetime(row["updated_at"], "updated_at"),
            completed_at=AsyncExternalPrototypeAgentStore._optional_datetime(
                row["completed_at"], "completed_at"
            ),
        )

    @staticmethod
    def _audit_from_row(row: aiosqlite.Row) -> ExternalAgentAuditEvent:
        duration = row["duration_ms"]
        if duration is not None:
            duration = AsyncExternalPrototypeAgentStore._integer(duration, "duration_ms")
        return ExternalAgentAuditEvent(
            id=AsyncExternalPrototypeAgentStore._string(row["id"], "id"),
            pairing_id=AsyncExternalPrototypeAgentStore._optional_string(
                row["pairing_id"], "pairing_id"
            ),
            project_id=AsyncExternalPrototypeAgentStore._string(row["project_id"], "project_id"),
            document_id=AsyncExternalPrototypeAgentStore._string(
                row["document_id"], "document_id"
            ),
            event_kind=AsyncExternalPrototypeAgentStore._string(
                row["event_kind"], "event_kind"
            ),
            tool_id=AsyncExternalPrototypeAgentStore._optional_string(row["tool_id"], "tool_id"),
            request_hash=AsyncExternalPrototypeAgentStore._optional_string(
                row["request_hash"], "request_hash"
            ),
            outcome=AsyncExternalPrototypeAgentStore._audit_outcome(row["outcome"]),
            error_code=AsyncExternalPrototypeAgentStore._optional_string(
                row["error_code"], "error_code"
            ),
            duration_ms=duration,
            occurred_at=AsyncExternalPrototypeAgentStore._datetime(
                row["occurred_at"], "occurred_at"
            ),
        )

    @staticmethod
    def _permissions(value: object) -> tuple[ExternalAgentPermission, ...]:
        if not isinstance(value, str):
            AsyncExternalPrototypeAgentStore._invalid_record("permissions_json")
        try:
            parsed: object = json.loads(value)
        except json.JSONDecodeError:
            AsyncExternalPrototypeAgentStore._invalid_record("permissions_json")
        if not isinstance(parsed, list) or not parsed or not all(
            isinstance(item, str) and item in {"prototype:read", "prototype:propose"}
            for item in parsed
        ):
            AsyncExternalPrototypeAgentStore._invalid_record("permissions_json")
        if len(parsed) != len(set(parsed)):
            AsyncExternalPrototypeAgentStore._invalid_record("permissions_json")
        return cast(tuple[ExternalAgentPermission, ...], tuple(parsed))

    @staticmethod
    def _agent_kind(value: object) -> ExternalAgentKind:
        if value not in {"claude_code", "codex"}:
            AsyncExternalPrototypeAgentStore._invalid_record("agent_kind")
        return value

    @staticmethod
    def _pairing_status(value: object) -> ExternalAgentPairingStatus:
        if value not in {"active", "revoked"}:
            AsyncExternalPrototypeAgentStore._invalid_record("status")
        return value

    @staticmethod
    def _submission_status(value: object) -> ExternalAgentSubmissionStatus:
        if value not in {"processing", "completed", "failed"}:
            AsyncExternalPrototypeAgentStore._invalid_record("status")
        return value

    @staticmethod
    def _audit_outcome(value: object) -> ExternalAgentAuditOutcome:
        if value not in {"ok", "error", "denied"}:
            AsyncExternalPrototypeAgentStore._invalid_record("outcome")
        return value

    @staticmethod
    def _string(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            AsyncExternalPrototypeAgentStore._invalid_record(field_name)
        return value

    @staticmethod
    def _optional_string(value: object, field_name: str) -> str | None:
        if value is None:
            return None
        return AsyncExternalPrototypeAgentStore._string(value, field_name)

    @staticmethod
    def _integer(value: object, field_name: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            AsyncExternalPrototypeAgentStore._invalid_record(field_name)
        return value

    @staticmethod
    def _datetime(value: object, field_name: str) -> datetime:
        raw = AsyncExternalPrototypeAgentStore._string(value, field_name)
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            AsyncExternalPrototypeAgentStore._invalid_record(field_name)
        if parsed.utcoffset() is None:
            AsyncExternalPrototypeAgentStore._invalid_record(field_name)
        return parsed

    @staticmethod
    def _optional_datetime(value: object, field_name: str) -> datetime | None:
        if value is None:
            return None
        return AsyncExternalPrototypeAgentStore._datetime(value, field_name)

    @staticmethod
    def _datetime_value(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _invalid_record(field_name: str) -> NoReturn:
        raise ExternalPrototypeAgentError(
            "external_agent_record_invalid",
            f"stored external Agent record has invalid {field_name}",
        )
