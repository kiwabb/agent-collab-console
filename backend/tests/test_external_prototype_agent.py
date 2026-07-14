from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import aiosqlite
import httpx
import pytest
from fastapi import FastAPI

from app.adapters.external_prototype_agent_store import AsyncExternalPrototypeAgentStore
from app.application.external_prototype_agent_contracts import (
    ActiveDesignContextResultV1,
    CreateExternalAgentPairingV1,
    DocumentSliceResultV1,
    ExternalProposalReceiptV1,
    ExternalProposalStatusResultV1,
    GetActiveDesignContextV1,
    GetDocumentSliceV1,
    GetExternalProposalStatusV1,
    StrictExternalAgentModel,
    SubmitExternalCommandProposalV1,
    ValidateExternalCommandBatchV1,
)
from app.application.external_prototype_agent_mcp import ExternalPrototypeAgentMcpHandler
from app.application.external_prototype_agent_service import (
    MCP_PATH,
    ExternalCommandValidationResult,
    ExternalPrototypeAgentError,
    ExternalPrototypeAgentService,
    UnavailableStructuredPrototypeCollaborationPort,
)
from app.domain.external_prototype_agent import ExternalAgentPairingRecord
from app.interfaces.external_prototype_agent_api import (
    get_external_prototype_agent_service,
    router,
)

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
DOCUMENT_HASH = "sha256:" + "a" * 64
VALIDATION_HASH = "sha256:" + "b" * 64
CLIENT_REQUEST_ID = "11111111-1111-1111-1111-111111111111"
SUBMISSION_REQUEST_ID = "22222222-2222-2222-2222-222222222222"


def parse_model[ModelT: StrictExternalAgentModel](
    model_type: type[ModelT],
    payload: object,
) -> ModelT:
    return model_type.model_validate(payload, strict=True, by_alias=True, by_name=False)


def pairing_request(
    *,
    permissions: list[str] | None = None,
    client_request_id: str = CLIENT_REQUEST_ID,
) -> CreateExternalAgentPairingV1:
    return parse_model(
        CreateExternalAgentPairingV1,
        {
            "protocolVersion": 1,
            "clientRequestId": client_request_id,
            "projectId": "project-1",
            "documentId": "document-1",
            "agentKind": "codex",
            "permissions": permissions or ["prototype:read", "prototype:propose"],
            "ttlSeconds": 300,
            "mcpUrl": f"http://127.0.0.1:8000{MCP_PATH}",
        },
    )


def submission_arguments(
    *,
    client_request_id: str = SUBMISSION_REQUEST_ID,
    message: str = "Adjust the primary action",
    affected_entity_ids: list[str] | None = None,
    expected_document_hash: str = DOCUMENT_HASH,
) -> dict[str, object]:
    return {
        "protocolVersion": 1,
        "draftId": "draft-1",
        "expectedHeadSequenceNo": 42,
        "expectedDocumentHash": expected_document_hash,
        "batch": {
            "commandContractVersion": 1,
            "summary": "Adjust the primary action",
            "commands": [
                {
                    "kind": "set_property",
                    "entityId": "node-1",
                    "property": "label",
                    "value": "Submit request",
                }
            ],
        },
        "clientRequestId": client_request_id,
        "message": message,
        "affectedEntityIds": affected_entity_ids or ["node-1"],
    }


class FakeStructuredPrototypeCore:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.validate_calls = 0
        self.force_scope_mismatch = False

    async def assert_pairing_scope(self, project_id: str, document_id: str) -> None:
        if (project_id, document_id) != ("project-1", "document-1"):
            raise ExternalPrototypeAgentError(
                "pairing_scope_invalid",
                "project and document are not available for pairing",
            )

    async def get_active_design_context(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetActiveDesignContextV1,
    ) -> ActiveDesignContextResultV1:
        del request
        project_id = "other-project" if self.force_scope_mismatch else pairing.project_id
        return parse_model(
            ActiveDesignContextResultV1,
            {
                "protocolVersion": 1,
                "projectId": project_id,
                "documentId": pairing.document_id,
                "revision": revision_payload(),
                "supportedCommandKinds": ["set_property"],
                "context": {"activePageId": "page-1", "selectedNodeIds": ["node-1"]},
                "truncated": False,
            },
        )

    async def get_document_slice(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetDocumentSliceV1,
    ) -> DocumentSliceResultV1:
        return parse_model(
            DocumentSliceResultV1,
            {
                "protocolVersion": 1,
                "projectId": pairing.project_id,
                "documentId": pairing.document_id,
                "revision": revision_payload(),
                "sliceKind": request.slice_kind,
                "data": {"entities": []},
                "truncated": False,
            },
        )

    async def validate_command_batch(
        self,
        pairing: ExternalAgentPairingRecord,
        request: ValidateExternalCommandBatchV1,
    ) -> ExternalCommandValidationResult:
        del pairing
        self.validate_calls += 1
        if (
            request.draft_id != "draft-1"
            or request.expected_head_sequence_no != 42
            or request.expected_document_hash != DOCUMENT_HASH
        ):
            raise ExternalPrototypeAgentError(
                "stale_base",
                "proposal base no longer matches the active draft",
            )
        return ExternalCommandValidationResult(
            affected_entity_ids=("node-1",),
            validation_hash=VALIDATION_HASH,
        )

    async def submit_command_proposal(
        self,
        pairing: ExternalAgentPairingRecord,
        request: SubmitExternalCommandProposalV1,
        request_hash: str,
        *,
        origin: Literal["external_agent"],
    ) -> ExternalProposalReceiptV1:
        del pairing, request
        assert origin == "external_agent"
        self.submit_calls += 1
        return parse_model(
            ExternalProposalReceiptV1,
            {
                "protocolVersion": 1,
                "proposalId": "proposal-1",
                "status": "preview_pending",
                "requestHash": request_hash,
                "submittedAt": NOW.isoformat(),
            },
        )

    async def get_proposal_status(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetExternalProposalStatusV1,
    ) -> ExternalProposalStatusResultV1:
        return parse_model(
            ExternalProposalStatusResultV1,
            {
                "protocolVersion": 1,
                "projectId": pairing.project_id,
                "documentId": pairing.document_id,
                "proposalId": request.proposal_id,
                "status": "preview_pending",
                "currentRevision": revision_payload(),
                "updatedAt": NOW.isoformat(),
            },
        )


def revision_payload() -> dict[str, object]:
    return {
        "draftId": "draft-1",
        "headSequenceNo": 42,
        "documentHash": DOCUMENT_HASH,
        "commandContractVersion": 1,
    }


async def create_service(
    db_path: Path,
    *,
    core: FakeStructuredPrototypeCore | UnavailableStructuredPrototypeCollaborationPort | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[
    ExternalPrototypeAgentService,
    AsyncExternalPrototypeAgentStore,
    FakeStructuredPrototypeCore | UnavailableStructuredPrototypeCollaborationPort,
]:
    store = AsyncExternalPrototypeAgentStore(db_path)
    collaboration = core or FakeStructuredPrototypeCore()
    service = ExternalPrototypeAgentService(
        store=store,
        collaboration=collaboration,
        clock=clock,
    )
    return service, store, collaboration


@pytest.mark.asyncio
async def test_unavailable_core_creates_no_pairing_state(tmp_path: Path) -> None:
    db_path = tmp_path / "unavailable.db"
    service, store, _ = await create_service(
        db_path,
        core=UnavailableStructuredPrototypeCollaborationPort(),
    )
    try:
        with pytest.raises(ExternalPrototypeAgentError, match="unavailable") as raised:
            await service.create_pairing(pairing_request())
        assert raised.value.code == "prototype_core_unavailable"
        assert not db_path.exists()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_pairing_persists_digest_without_bearer(tmp_path: Path) -> None:
    db_path = tmp_path / "pairing.db"
    service, store, _ = await create_service(db_path)
    try:
        issued = await service.create_pairing(pairing_request())
        expected_digest = "sha256:" + hashlib.sha256(
            issued.bearer_token.encode("utf-8")
        ).hexdigest()
        assert issued.pairing.token_digest == expected_digest
        assert issued.bearer_token not in issued.pairing.token_digest
        loaded = await store.load_pairing_by_token_digest(expected_digest)
        assert loaded is not None and loaded.id == issued.pairing.id

        async with aiosqlite.connect(db_path) as connection:
            row = await (
                await connection.execute(
                    "SELECT token_digest, permissions_json FROM external_prototype_agent_pairings"
                )
            ).fetchone()
        assert row is not None
        assert issued.bearer_token not in "|".join(str(value) for value in row)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_pairing_expiry_and_revocation_fail_closed(tmp_path: Path) -> None:
    current = [NOW]
    service, store, _ = await create_service(tmp_path / "lifecycle.db", clock=lambda: current[0])
    try:
        issued = await service.create_pairing(pairing_request())
        current[0] = NOW + timedelta(seconds=301)
        with pytest.raises(ExternalPrototypeAgentError) as expired:
            await service.authorize_pairing(issued.bearer_token)
        assert expired.value.code == "pairing_expired"

        current[0] = NOW
        second = await service.create_pairing(
            pairing_request(client_request_id="33333333-3333-3333-3333-333333333333")
        )
        await service.revoke_pairing(second.pairing.id)
        with pytest.raises(ExternalPrototypeAgentError) as revoked:
            await service.authorize_pairing(second.bearer_token)
        assert revoked.value.code == "pairing_revoked"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_mcp_lists_only_pairing_permissions_and_audits_denial(tmp_path: Path) -> None:
    service, store, _ = await create_service(tmp_path / "permissions.db")
    try:
        issued = await service.create_pairing(
            pairing_request(permissions=["prototype:read"])
        )
        handler = ExternalPrototypeAgentMcpHandler(service)
        initialized = await handler.handle(
            issued.pairing,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-agent", "version": "1"},
                },
            },
        )
        assert initialized.body is not None
        initialized_result = initialized.body["result"]
        assert isinstance(initialized_result, dict)
        assert initialized_result["protocolVersion"] == "2025-06-18"
        listed = await handler.handle(
            issued.pairing,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert listed.body is not None
        listed_result = listed.body["result"]
        assert isinstance(listed_result, dict)
        tools = listed_result["tools"]
        assert isinstance(tools, list)
        tool_records: list[dict[str, object]] = []
        for tool in tools:
            assert isinstance(tool, dict)
            tool_records.append(tool)
        names = {tool["name"] for tool in tool_records}
        assert "get_active_design_context" in names
        assert "submit_command_proposal" not in names
        for tool in tool_records:
            input_schema = tool["inputSchema"]
            assert isinstance(input_schema, dict)
            assert input_schema["additionalProperties"] is False

        denied = await handler.handle(
            issued.pairing,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "submit_command_proposal", "arguments": {}},
            },
        )
        assert denied.body is not None
        denied_result = denied.body["result"]
        assert isinstance(denied_result, dict)
        assert denied_result["isError"] is True
        structured_content = denied_result["structuredContent"]
        assert isinstance(structured_content, dict)
        error = structured_content["error"]
        assert isinstance(error, dict)
        assert error["code"] == "tool_not_allowed"

        async with aiosqlite.connect(tmp_path / "permissions.db") as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT outcome, error_code FROM external_prototype_agent_audit_events
                    WHERE tool_id = 'submit_command_proposal'
                    """
                )
            ).fetchone()
        assert row == ("denied", "tool_not_allowed")
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_context_response_cannot_escape_pairing_scope(tmp_path: Path) -> None:
    core = FakeStructuredPrototypeCore()
    core.force_scope_mismatch = True
    service, store, _ = await create_service(tmp_path / "scope.db", core=core)
    try:
        issued = await service.create_pairing(pairing_request())
        with pytest.raises(ExternalPrototypeAgentError) as raised:
            await service.invoke_tool(
                issued.pairing,
                "get_active_design_context",
                {
                    "protocolVersion": 1,
                    "scope": {
                        "pageId": "page-1",
                        "selectedNodeIds": ["node-1"],
                        "flowId": None,
                        "viewport": "desktop",
                    },
                },
            )
        assert raised.value.code == "prototype_response_scope_mismatch"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_pairing_rejects_wrong_project_or_document_before_persistence(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "wrong-scope.db"
    service, store, _ = await create_service(db_path)
    payload = pairing_request().model_dump(mode="json", by_alias=True)
    payload["projectId"] = "other-project"
    request = parse_model(CreateExternalAgentPairingV1, payload)
    try:
        with pytest.raises(ExternalPrototypeAgentError) as raised:
            await service.create_pairing(request)
        assert raised.value.code == "pairing_scope_invalid"
        assert not db_path.exists()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_identical_submission_is_idempotent_and_changed_retry_conflicts(
    tmp_path: Path,
) -> None:
    core = FakeStructuredPrototypeCore()
    service, store, _ = await create_service(tmp_path / "idempotency.db", core=core)
    try:
        issued = await service.create_pairing(pairing_request())
        first = await service.invoke_tool(
            issued.pairing,
            "submit_command_proposal",
            submission_arguments(),
        )
        second = await service.invoke_tool(
            issued.pairing,
            "submit_command_proposal",
            submission_arguments(),
        )
        assert first == second
        assert core.submit_calls == 1

        with pytest.raises(ExternalPrototypeAgentError) as conflict:
            await service.invoke_tool(
                issued.pairing,
                "submit_command_proposal",
                submission_arguments(message="Changed retry"),
            )
        assert conflict.value.code == "submission_conflict"
        assert core.submit_calls == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_mismatched_affected_ids_and_stale_base_create_no_submission(
    tmp_path: Path,
) -> None:
    service, store, _ = await create_service(tmp_path / "validation.db")
    try:
        issued = await service.create_pairing(pairing_request())
        with pytest.raises(ExternalPrototypeAgentError) as mismatch:
            await service.invoke_tool(
                issued.pairing,
                "submit_command_proposal",
                submission_arguments(affected_entity_ids=["node-2"]),
            )
        assert mismatch.value.code == "affected_entities_mismatch"

        with pytest.raises(ExternalPrototypeAgentError) as stale:
            await service.invoke_tool(
                issued.pairing,
                "submit_command_proposal",
                submission_arguments(
                    client_request_id="44444444-4444-4444-4444-444444444444",
                    expected_document_hash="sha256:" + "c" * 64,
                ),
            )
        assert stale.value.code == "stale_base"

        async with aiosqlite.connect(tmp_path / "validation.db") as connection:
            row = await (
                await connection.execute(
                    "SELECT COUNT(*) FROM external_prototype_agent_submissions"
                )
            ).fetchone()
        assert row == (0,)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_audit_and_submission_storage_exclude_prompt_and_command_bodies(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "safe-audit.db"
    service, store, _ = await create_service(db_path)
    marker = "DO_NOT_PERSIST_SECRET_MARKER"
    try:
        issued = await service.create_pairing(pairing_request())
        arguments = submission_arguments(message=marker)
        batch = arguments["batch"]
        assert isinstance(batch, dict)
        commands = batch["commands"]
        assert isinstance(commands, list)
        command = commands[0]
        assert isinstance(command, dict)
        command["value"] = marker
        await service.invoke_tool(
            issued.pairing,
            "submit_command_proposal",
            arguments,
        )
        async with aiosqlite.connect(db_path) as connection:
            event_columns = await (
                await connection.execute(
                    "PRAGMA table_info(external_prototype_agent_audit_events)"
                )
            ).fetchall()
            event_rows = await (
                await connection.execute(
                    "SELECT * FROM external_prototype_agent_audit_events"
                )
            ).fetchall()
        column_names = {row[1] for row in event_columns}
        assert not {"prompt", "command_json", "document_json", "bearer_token"} & column_names
        assert marker not in repr(event_rows)
        assert marker.encode() not in db_path.read_bytes()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_external_prototype_agent_service] = lambda: service
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8000",
        ) as client:
            response = await client.get(
                "/api/external-prototype-agent/audit-events",
                params={"projectId": "project-1", "documentId": "document-1"},
            )
        assert response.status_code == 200
        assert response.json()["items"]
        assert marker not in response.text
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_mcp_http_rejects_non_loopback_and_accepts_valid_loopback_pairing(
    tmp_path: Path,
) -> None:
    service, store, _ = await create_service(tmp_path / "http.db")
    issued = await service.create_pairing(pairing_request())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_external_prototype_agent_service] = lambda: service
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-agent", "version": "1"},
        },
    }
    headers = {"Authorization": f"Bearer {issued.bearer_token}"}
    try:
        remote_transport = httpx.ASGITransport(app=app, client=("10.0.0.2", 1234))
        async with httpx.AsyncClient(
            transport=remote_transport,
            base_url="http://127.0.0.1:8000",
        ) as remote:
            rejected = await remote.post(MCP_PATH, json=payload, headers=headers)
        assert rejected.status_code == 403
        assert rejected.json()["error"]["data"]["code"] == "loopback_required"

        local_transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(
            transport=local_transport,
            base_url="http://127.0.0.1:8000",
        ) as local:
            accepted = await local.post(MCP_PATH, json=payload, headers=headers)
        assert accepted.status_code == 200
        assert accepted.json()["result"]["serverInfo"]["name"] == "prototype-collaboration"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_pairing_api_reports_unavailable_core_without_state(tmp_path: Path) -> None:
    db_path = tmp_path / "api-unavailable.db"
    service, store, _ = await create_service(
        db_path,
        core=UnavailableStructuredPrototypeCollaborationPort(),
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_external_prototype_agent_service] = lambda: service
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8000",
        ) as client:
            response = await client.post(
                "/api/external-prototype-agent/pairings",
                json=pairing_request().model_dump(mode="json", by_alias=True),
            )
        assert response.status_code == 503
        assert response.json() == {
            "detail": "prototype_core_unavailable",
            "retryable": True,
        }
        assert not db_path.exists()
    finally:
        await store.close()
